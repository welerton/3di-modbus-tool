"""
Descoberta automática da configuração serial Modbus RTU (roda em segundo
plano na interface, com progresso e cancelamento).

Testa combinações de baudrate, paridade, stop bits e ID do escravo enviando
leituras (FC03/FC04) e validando a resposta pelo CRC. Modbus RTU usa sempre
8 data bits.
"""

import itertools
import time
from dataclasses import dataclass

import serial

from .protocol import PARITY_MAP, crc16, pdu_leitura, silencio_rtu, tamanho_resposta_rtu


@dataclass
class Achado:
    status: str            # "ok" (dados válidos) ou "excecao" (respondeu com exceção Modbus)
    porta: str
    baud: int
    paridade: str
    stopbits: int
    escravo: int
    fc: int
    detalhe: str


def faixa_escravos(texto: str) -> list[int]:
    """Aceita '1-32', '1,2,5', '1-10,247'."""
    ids = set()
    for parte in texto.split(","):
        parte = parte.strip()
        if not parte:
            continue
        if "-" in parte:
            a, b = parte.split("-", 1)
            ids.update(range(int(a), int(b) + 1))
        else:
            ids.add(int(parte))
    invalidos = [i for i in ids if not 1 <= i <= 247]
    if invalidos:
        raise ValueError(f"IDs fora de 1-247: {invalidos[:5]}")
    return sorted(ids)


def _testa(ser, baud, escravo, fc, endereco, qtd):
    """Envia uma leitura e classifica a resposta: ('ok', valores) | ('excecao', código) | (None, None)."""
    quadro = bytes([escravo]) + pdu_leitura(fc, endereco, qtd)
    quadro += crc16(quadro)
    ser.reset_input_buffer()
    ser.write(quadro)
    inicio = ser.read(3)
    if len(inicio) < 3 or inicio[0] != escravo:
        time.sleep(silencio_rtu(baud))
        return None, None
    resto = ser.read(max(0, tamanho_resposta_rtu(fc, inicio) - 3))
    resp = inicio + resto
    time.sleep(silencio_rtu(baud))
    if len(resp) < 5 or crc16(resp[:-2]) != resp[-2:]:
        return None, None
    if resp[1] == fc and resp[2] == 2 * qtd:
        valores = [int.from_bytes(resp[3 + 2 * i:5 + 2 * i], "big") for i in range(qtd)]
        return "ok", valores
    if resp[1] == (fc | 0x80):
        return "excecao", resp[2]
    return None, None


def varre(porta, baudrates, paridades, stopbits, escravos, funcoes, endereco=0, qtd=1,
          timeout=0.15, parar_apos=1, cancelado=lambda: False,
          ao_log=lambda msg: None, ao_progresso=lambda feito, total: None) -> list[Achado]:
    achados: list[Achado] = []
    combos = list(itertools.product(baudrates, paridades, stopbits))
    total = len(combos) * len(escravos) * len(funcoes)
    feito = 0
    t0 = time.time()

    for i, (baud, par, sb) in enumerate(combos, 1):
        if cancelado():
            ao_log("Varredura cancelada.")
            return achados
        try:
            ser = serial.Serial(port=porta, baudrate=baud, parity=PARITY_MAP[par], stopbits=sb,
                                bytesize=8, timeout=timeout, write_timeout=1)
        except serial.SerialException as e:
            ao_log(f"Erro ao abrir {porta}: {e}")
            return achados
        ao_log(f"[{i}/{len(combos)}] {baud} bps · paridade {par} · {sb} stop bit(s)")
        try:
            for escravo in escravos:
                for fc in funcoes:
                    if cancelado():
                        ao_log("Varredura cancelada.")
                        return achados
                    status, info = _testa(ser, baud, escravo, fc, endereco, qtd)
                    feito += 1
                    ao_progresso(feito, total)
                    if status == "ok":
                        a = Achado("ok", porta, baud, par, sb, escravo, fc, f"valores {info}")
                        achados.append(a)
                        ao_log(f"   >> RESPOSTA VÁLIDA: ID {escravo}, FC{fc:02d}, valores {info}")
                    elif status == "excecao":
                        a = Achado("excecao", porta, baud, par, sb, escravo, fc,
                                   f"exceção {info} (serial e ID corretos; endereço/quantidade não aceitos)")
                        achados.append(a)
                        ao_log(f"   >> Respondeu com exceção {info}: ID {escravo}, FC{fc:02d}")
                    if parar_apos and sum(1 for x in achados if x.status == "ok") >= parar_apos:
                        ao_log(f"Encontrado(s) {parar_apos} dispositivo(s) — varredura encerrada.")
                        return achados
        finally:
            ser.close()

    ao_log(f"Varredura concluída em {time.time() - t0:.1f} s.")
    return achados
