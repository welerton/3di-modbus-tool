"""
Thread de comunicação: executa as leituras periódicas de cada janela e as
escritas pedidas pelo usuário, sempre uma transação por vez no barramento.
"""

import itertools
import queue
import threading
import time
from dataclasses import dataclass, field, asdict

from PySide6.QtCore import QObject, Signal

from .protocol import ModbusExcecao, ModbusTimeout, ModbusErroQuadro, pdu_leitura


@dataclass
class Definicao:
    escravo: int = 1
    fc: int = 3
    endereco: int = 0
    qtd: int = 10
    scan_ms: int = 1000
    base1: bool = False
    ativo: bool = True

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class _Leitura:
    definicao: Definicao
    proxima: float = 0.0
    tx: int = 0
    err: int = 0


def texto_erro(e: Exception) -> str:
    if isinstance(e, ModbusExcecao):
        return str(e)
    if isinstance(e, ModbusTimeout):
        return "Timeout: o dispositivo não respondeu"
    if isinstance(e, ModbusErroQuadro):
        return f"Resposta inválida: {e}"
    return f"Erro de comunicação: {e}"


class Comunicador(QObject):
    # (id_janela, dados) — dados: {"ok", "valores"|"erro", "tx", "err"}
    leitura = Signal(int, object)
    # (contexto, erro ou "")
    escrita = Signal(object, str)
    # (direção "Tx"/"Rx", bytes, timestamp)
    trafego = Signal(str, bytes, float)
    # (conectado, descrição/erro)
    conexao = Signal(bool, str)

    def __init__(self):
        super().__init__()
        self.transporte = None
        self.atraso_ms = 20
        self._leituras: dict[int, _Leitura] = {}
        self._escritas: "queue.Queue" = queue.Queue()
        self._lock = threading.Lock()
        self._rodando = True
        self._ids = itertools.count(1)
        self._thread = threading.Thread(target=self._loop, daemon=True, name="modbus")
        self._thread.start()

    # ── conexão ──────────────────────────────────────────────────────────────
    def conectar(self, transporte):
        self.desconectar()
        transporte.ao_trafegar = lambda d, b: self.trafego.emit(d, bytes(b), time.time())
        transporte.abrir()          # pode levantar exceção (porta ocupada, IP inacessível...)
        with self._lock:
            self.transporte = transporte
            for l in self._leituras.values():
                l.proxima = 0.0
        self.conexao.emit(True, transporte.descricao())

    def desconectar(self):
        with self._lock:
            t, self.transporte = self.transporte, None
        if t:
            with t.lock:
                t.fechar()
            self.conexao.emit(False, "Desconectado")

    @property
    def conectado(self):
        return self.transporte is not None

    # ── leituras ─────────────────────────────────────────────────────────────
    def nova_leitura(self, definicao: Definicao) -> int:
        i = next(self._ids)
        with self._lock:
            self._leituras[i] = _Leitura(definicao)
        return i

    def atualiza_leitura(self, i: int, definicao: Definicao, zerar=False):
        with self._lock:
            l = self._leituras.get(i)
            if l:
                l.definicao = definicao
                l.proxima = 0.0
                if zerar:
                    l.tx = l.err = 0

    def zera_contadores(self, i: int):
        with self._lock:
            l = self._leituras.get(i)
            if l:
                l.tx = l.err = 0

    def ler_agora(self, i: int):
        with self._lock:
            l = self._leituras.get(i)
            if l:
                l.proxima = 0.0

    def remove_leitura(self, i: int):
        with self._lock:
            self._leituras.pop(i, None)

    # ── escritas ─────────────────────────────────────────────────────────────
    def escrever(self, escravo: int, pdu: bytes, contexto=None):
        self._escritas.put((escravo, pdu, contexto))

    # ── laço ─────────────────────────────────────────────────────────────────
    def parar(self):
        self._rodando = False
        self.desconectar()

    def _loop(self):
        while self._rodando:
            t = self.transporte
            if t is None:
                # sem conexão: escritas pendentes falham na hora
                try:
                    _, _, ctx = self._escritas.get_nowait()
                    self.escrita.emit(ctx, "Sem conexão")
                except queue.Empty:
                    time.sleep(0.05)
                continue

            try:
                escravo, pdu, ctx = self._escritas.get_nowait()
            except queue.Empty:
                escravo = None
            if escravo is not None:
                try:
                    t.executa(escravo, pdu)
                    self.escrita.emit(ctx, "")
                except Exception as e:
                    self.escrita.emit(ctx, texto_erro(e))
                time.sleep(self.atraso_ms / 1000)
                continue

            agora = time.monotonic()
            with self._lock:
                pendentes = [(l.proxima, i, l) for i, l in self._leituras.items()
                             if l.definicao.ativo and l.proxima <= agora]
            if not pendentes:
                time.sleep(0.01)
                continue
            _, i, l = min(pendentes, key=lambda x: x[0])
            d = l.definicao
            l.tx += 1
            try:
                valores = t.executa(d.escravo, pdu_leitura(d.fc, d.endereco, d.qtd))
                dados = {"ok": True, "valores": valores}
            except Exception as e:
                l.err += 1
                dados = {"ok": False, "erro": texto_erro(e)}
            dados.update(tx=l.tx, err=l.err)
            l.proxima = time.monotonic() + d.scan_ms / 1000
            self.leitura.emit(i, dados)
            time.sleep(self.atraso_ms / 1000)
