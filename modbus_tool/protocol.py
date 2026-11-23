"""
Camada de protocolo Modbus (RTU serial e TCP) implementada direto sobre
pyserial / socket, para ter controle total dos bytes (janela de tráfego).
"""

import socket
import struct
import threading
import time

import serial
import serial.tools.list_ports

PARITY_MAP = {"N": serial.PARITY_NONE, "E": serial.PARITY_EVEN, "O": serial.PARITY_ODD}
PARITY_NAME = {"N": "Nenhuma", "E": "Par (Even)", "O": "Ímpar (Odd)"}
BAUDRATES = [1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200]

FUNCOES_LEITURA = {
    1: "01 Read Coils (0x)",
    2: "02 Read Discrete Inputs (1x)",
    3: "03 Read Holding Registers (4x)",
    4: "04 Read Input Registers (3x)",
}
# prefixo usado no endereçamento "estilo CLP" (base 1): 0xxxx, 1xxxx, 4xxxx, 3xxxx
PREFIXO_PLC = {1: 0, 2: 100000, 3: 400000, 4: 300000}

EXCECOES = {
    1: "Função ilegal",
    2: "Endereço de dados ilegal",
    3: "Valor de dados ilegal",
    4: "Falha no dispositivo escravo",
    5: "Reconhecido (processando)",
    6: "Escravo ocupado",
    8: "Erro de paridade de memória",
    10: "Gateway: caminho indisponível",
    11: "Gateway: dispositivo não respondeu",
}


class ModbusExcecao(Exception):
    """O escravo respondeu com uma exceção Modbus."""

    def __init__(self, codigo: int):
        self.codigo = codigo
        super().__init__(f"Exceção Modbus {codigo:02d}: {EXCECOES.get(codigo, 'desconhecida')}")


class ModbusTimeout(Exception):
    """Sem resposta dentro do tempo limite."""


class ModbusErroQuadro(Exception):
    """Resposta recebida, mas inválida (CRC, tamanho, ID ou função errados)."""


# ── CRC / PDUs ────────────────────────────────────────────────────────────────

def crc16(data: bytes) -> bytes:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return struct.pack("<H", crc)


def pdu_leitura(fc: int, endereco: int, qtd: int) -> bytes:
    return struct.pack(">BHH", fc, endereco, qtd)


def pdu_escreve_bobina(endereco: int, ligado: bool) -> bytes:
    return struct.pack(">BHH", 5, endereco, 0xFF00 if ligado else 0x0000)


def pdu_escreve_registrador(endereco: int, valor: int) -> bytes:
    return struct.pack(">BHH", 6, endereco, valor & 0xFFFF)


def pdu_escreve_registradores(endereco: int, valores: list[int]) -> bytes:
    n = len(valores)
    return struct.pack(f">BHHB{n}H", 16, endereco, n, 2 * n, *[v & 0xFFFF for v in valores])


def pdu_escreve_bobinas(endereco: int, bits: list[bool]) -> bytes:
    n = len(bits)
    dados = bytearray((n + 7) // 8)
    for i, b in enumerate(bits):
        if b:
            dados[i // 8] |= 1 << (i % 8)
    return struct.pack(">BHHB", 15, endereco, n, len(dados)) + bytes(dados)


def interpreta_resposta(req: bytes, resp: bytes):
    """Valida o PDU de resposta contra o PDU enviado. Retorna lista de valores (leitura) ou None."""
    fc = req[0]
    if not resp:
        raise ModbusErroQuadro("resposta vazia")
    if resp[0] == (fc | 0x80):
        raise ModbusExcecao(resp[1] if len(resp) > 1 else 0)
    if resp[0] != fc:
        raise ModbusErroQuadro(f"função na resposta ({resp[0]}) diferente da enviada ({fc})")
    if fc in (1, 2, 3, 4):
        qtd = struct.unpack(">H", req[3:5])[0]
        nbytes = resp[1]
        dados = resp[2:2 + nbytes]
        if len(dados) != nbytes:
            raise ModbusErroQuadro("tamanho de dados incoerente")
        if fc in (3, 4):
            if nbytes != 2 * qtd:
                raise ModbusErroQuadro(f"esperava {2 * qtd} bytes, recebeu {nbytes}")
            return list(struct.unpack(f">{qtd}H", dados))
        bits = [(dados[i // 8] >> (i % 8)) & 1 for i in range(qtd)]
        if nbytes != (qtd + 7) // 8:
            raise ModbusErroQuadro("quantidade de bytes de bits incoerente")
        return bits
    # escritas: eco de endereço/quantidade
    if resp[1:5] != req[1:5]:
        raise ModbusErroQuadro("eco da escrita não confere")
    return None


def tamanho_resposta_rtu(fc: int, inicio: bytes) -> int:
    """Com os 3 primeiros bytes da resposta RTU, devolve o tamanho total do quadro."""
    if inicio[1] & 0x80:
        return 5                      # id, fc|80, código, crc(2)
    if fc in (1, 2, 3, 4):
        return 3 + inicio[2] + 2      # id, fc, nbytes, dados, crc
    return 8                          # escritas: id, fc, end(2), qtd/valor(2), crc


def silencio_rtu(baud: int) -> float:
    """3,5 caracteres de silêncio entre quadros (spec Modbus RTU)."""
    return 0.00175 if baud > 19200 else 3.5 * 11.0 / baud


def lista_portas():
    return sorted(serial.tools.list_ports.comports(), key=lambda p: p.device)


# ── Transportes ───────────────────────────────────────────────────────────────

class Transporte:
    """Base: mantém contadores e avisa o tráfego (direção, bytes) ao callback."""

    def __init__(self, ao_trafegar=None):
        self.ao_trafegar = ao_trafegar or (lambda d, b: None)
        self.lock = threading.Lock()

    def descricao(self) -> str:
        raise NotImplementedError

    def abrir(self):
        raise NotImplementedError

    def fechar(self):
        raise NotImplementedError

    def transacao(self, escravo: int, pdu: bytes) -> bytes:
        raise NotImplementedError

    def executa(self, escravo: int, pdu: bytes):
        """Envia um PDU, valida a resposta e devolve valores (leitura) ou None."""
        with self.lock:
            resp = self.transacao(escravo, pdu)
        return interpreta_resposta(pdu, resp)


class TransporteRTU(Transporte):
    def __init__(self, porta, baud=9600, paridade="N", stopbits=1, bytesize=8,
                 timeout=1.0, ao_trafegar=None):
        super().__init__(ao_trafegar)
        self.porta, self.baud, self.paridade = porta, baud, paridade
        self.stopbits, self.bytesize, self.timeout = stopbits, bytesize, timeout
        self.ser = None
        self._ultimo = 0.0

    def descricao(self):
        return f"{self.porta}: {self.baud}-{self.bytesize}-{self.paridade}-{self.stopbits}"

    def abrir(self):
        self.ser = serial.Serial(port=self.porta, baudrate=self.baud, parity=PARITY_MAP[self.paridade],
                                 stopbits=self.stopbits, bytesize=self.bytesize,
                                 timeout=self.timeout, write_timeout=1)

    def fechar(self):
        if self.ser:
            self.ser.close()
            self.ser = None

    def transacao(self, escravo, pdu):
        if not self.ser:
            raise ConnectionError("porta serial fechada")
        quadro = bytes([escravo]) + pdu
        quadro += crc16(quadro)
        espera = silencio_rtu(self.baud) - (time.perf_counter() - self._ultimo)
        if espera > 0:
            time.sleep(espera)
        self.ser.reset_input_buffer()
        self.ser.write(quadro)
        self.ao_trafegar("Tx", quadro)

        inicio = self.ser.read(3)
        if len(inicio) < 3:
            self._ultimo = time.perf_counter()
            if inicio:
                self.ao_trafegar("Rx", inicio)
            raise ModbusTimeout("sem resposta (timeout)")
        resto = self.ser.read(tamanho_resposta_rtu(pdu[0], inicio) - 3)
        self._ultimo = time.perf_counter()
        resp = inicio + resto
        self.ao_trafegar("Rx", resp)
        if len(resp) < tamanho_resposta_rtu(pdu[0], inicio):
            raise ModbusTimeout("resposta incompleta (timeout)")
        if crc16(resp[:-2]) != resp[-2:]:
            raise ModbusErroQuadro("erro de CRC")
        if escravo != 0 and resp[0] != escravo:
            raise ModbusErroQuadro(f"respondeu o ID {resp[0]}, esperado {escravo}")
        return resp[1:-2]


class TransporteTCP(Transporte):
    def __init__(self, host, porta=502, timeout=1.0, ao_trafegar=None):
        super().__init__(ao_trafegar)
        self.host, self.porta, self.timeout = host, porta, timeout
        self.sock = None
        self._tid = 0

    def descricao(self):
        return f"TCP {self.host}:{self.porta}"

    def abrir(self):
        self.sock = socket.create_connection((self.host, self.porta), timeout=max(self.timeout, 2.0))
        self.sock.settimeout(self.timeout)

    def fechar(self):
        if self.sock:
            try:
                self.sock.close()
            finally:
                self.sock = None

    def _recebe(self, n):
        dados = b""
        while len(dados) < n:
            parte = self.sock.recv(n - len(dados))
            if not parte:
                raise ConnectionError("conexão fechada pelo servidor")
            dados += parte
        return dados

    def transacao(self, escravo, pdu):
        if not self.sock:
            self.abrir()          # reconecta sozinho se o servidor derrubou a conexão
        self._tid = (self._tid + 1) & 0xFFFF
        quadro = struct.pack(">HHHB", self._tid, 0, len(pdu) + 1, escravo) + pdu
        try:
            self.sock.sendall(quadro)
            self.ao_trafegar("Tx", quadro)
            while True:
                cab = self._recebe(7)
                tid, _, tam, _uid = struct.unpack(">HHHB", cab)
                corpo = self._recebe(tam - 1)
                self.ao_trafegar("Rx", cab + corpo)
                if tid == self._tid:
                    return corpo
                # resposta atrasada de uma transação anterior: descarta e espera a certa
        except socket.timeout:
            self.fechar()
            raise ModbusTimeout("sem resposta (timeout)")
        except OSError:
            self.fechar()
            raise
