"""Janela principal (MDI, estilo Modbus Poll) e janelas de leitura."""

import json
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QColor, QFont, QKeySequence, QBrush
from PySide6.QtWidgets import (
    QMainWindow, QMdiArea, QMdiSubWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QMenu, QMessageBox, QFileDialog, QDockWidget,
    QPlainTextEdit, QPushButton, QCheckBox, QApplication, QStyle,
)

from . import formatos as F
from .comunicacao import Comunicador, Definicao
from .dialogos import (DialogoConexao, DialogoDefinicao, DialogoDescoberta, DialogoEscritaCelula,
                       DialogoEscritaManual)
from .protocol import PREFIXO_PLC, PARITY_NAME, TransporteRTU, TransporteTCP

NOME_APP = "3Di Modbus Tool"
PASTA = Path(__file__).resolve().parent.parent
SESSAO = PASTA / "ultima_sessao.json"
PASTA_WS = PASTA / "workspaces"
MONO = QFont("Consolas", 10)
COR_ERRO = "#C62828"
COR_CONT = QColor("#9E9E9E")


def rotulo_endereco(d: Definicao, i: int) -> str:
    end = d.endereco + i
    if not d.base1:
        return str(end)
    dig = PREFIXO_PLC[d.fc] // 100000
    return f"{dig}{end + 1:04d}" if end + 1 <= 9999 else f"{dig}{end + 1:05d}"


# ── Janela de leitura ─────────────────────────────────────────────────────────

class JanelaLeitura(QWidget):
    COL_ALIAS, COL_END, COL_VALOR = range(3)

    def __init__(self, principal, definicao: Definicao, aliases=None, formatos=None):
        super().__init__()
        self.principal = principal
        self.com: Comunicador = principal.com
        self.d = definicao
        self.aliases = list(aliases or [])
        self.formatos = list(formatos or [])
        self.valores = None
        self.ultimo_ok = None
        self.id = self.com.nova_leitura(self.d)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(2)
        self.lb_cab = QLabel()
        self.lb_cab.setFont(MONO)
        self.lb_status = QLabel()
        self.lb_status.setFont(MONO)
        lay.addWidget(self.lb_cab)
        lay.addWidget(self.lb_status)

        self.tab = QTableWidget(0, 3)
        self.tab.setHorizontalHeaderLabels(["Alias", "Endereço", "Valor"])
        self.tab.verticalHeader().setVisible(False)
        self.tab.verticalHeader().setDefaultSectionSize(22)
        self.tab.setFont(MONO)
        h = self.tab.horizontalHeader()
        h.setSectionResizeMode(self.COL_ALIAS, QHeaderView.Interactive)
        h.setSectionResizeMode(self.COL_END, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(self.COL_VALOR, QHeaderView.Stretch)
        self.tab.setColumnWidth(self.COL_ALIAS, 170)
        self.tab.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tab.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.tab.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tab.customContextMenuRequested.connect(self._menu_contexto)
        self.tab.cellDoubleClicked.connect(self._duplo_clique)
        self.tab.itemChanged.connect(self._alias_editado)
        lay.addWidget(self.tab)

        self._monta_linhas()
        self._atualiza_cabecalho(0, 0)
        self._mostra_status()

    # ── estrutura ────────────────────────────────────────────────────────────
    @property
    def bits(self):
        return self.d.fc in (1, 2)

    def _monta_linhas(self):
        n = self.d.qtd
        self.aliases = (self.aliases + [""] * n)[:n]
        self.formatos = (self.formatos + [F.FORMATO_PADRAO] * n)[:n]
        self.tab.blockSignals(True)
        self.tab.setRowCount(n)
        for i in range(n):
            a = QTableWidgetItem(self.aliases[i])
            e = QTableWidgetItem(rotulo_endereco(self.d, i))
            e.setFlags(e.flags() & ~Qt.ItemIsEditable)
            e.setForeground(QBrush(QColor("#555")))
            v = QTableWidgetItem("")
            v.setFlags(v.flags() & ~Qt.ItemIsEditable)
            v.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tab.setItem(i, self.COL_ALIAS, a)
            self.tab.setItem(i, self.COL_END, e)
            self.tab.setItem(i, self.COL_VALOR, v)
        self.tab.blockSignals(False)
        self._preenche_valores()
        self._atualiza_titulo()

    def _atualiza_titulo(self):
        sub = self.parentWidget()
        titulo = f"ID {self.d.escravo} · FC{self.d.fc:02d} · {rotulo_endereco(self.d, 0)} ({self.d.qtd})"
        if not self.d.ativo:
            titulo += " · PAUSADA"
        self.setWindowTitle(titulo)
        if isinstance(sub, QMdiSubWindow):
            sub.setWindowTitle(titulo)

    def _atualiza_cabecalho(self, tx, err):
        self.lb_cab.setText(f"Tx = {tx}: Err = {err}: ID = {self.d.escravo}: F = {self.d.fc:02d}: SR = {self.d.scan_ms}ms")

    def _mostra_status(self, erro=None):
        if not self.com.conectado:
            texto, cor = "Sem conexão", COR_ERRO
        elif not self.d.ativo:
            texto, cor = "Leitura pausada", "#E65100"
        elif erro:
            texto, cor = erro, COR_ERRO
        elif self.ultimo_ok:
            texto, cor = f"OK · última leitura {self.ultimo_ok}", "#2E7D32"
        else:
            texto, cor = "Aguardando leitura...", "#555"
        self.lb_status.setText(texto)
        self.lb_status.setStyleSheet(f"color: {cor}")

    # ── dados ────────────────────────────────────────────────────────────────
    def recebe(self, dados):
        self._atualiza_cabecalho(dados["tx"], dados["err"])
        if dados["ok"]:
            self.valores = dados["valores"]
            self.ultimo_ok = datetime.now().strftime("%H:%M:%S")
            self._preenche_valores()
            self._mostra_status()
        else:
            self._mostra_status(dados["erro"])
            self._marca_desatualizado()

    def _marca_desatualizado(self):
        for i in range(self.tab.rowCount()):
            it = self.tab.item(i, self.COL_VALOR)
            if it and it.text() and it.foreground().color() != COR_CONT:
                it.setForeground(QBrush(QColor("#B0B0B0")))

    def _preenche_valores(self):
        if self.valores is None:
            return
        i = 0
        n = len(self.valores)
        while i < self.tab.rowCount():
            it = self.tab.item(i, self.COL_VALOR)
            it.setForeground(QBrush(QColor("black")))
            if i >= n:
                it.setText("")
                i += 1
                continue
            if self.bits:
                it.setText(str(self.valores[i]))
                i += 1
                continue
            fmt = self.formatos[i]
            k = F.n_registradores(fmt)
            if i + k > n:
                it.setText("(faltam registradores)")
                it.setForeground(QBrush(QColor(COR_ERRO)))
                i += 1
                continue
            it.setText(F.formata(self.valores[i:i + k], fmt))
            for j in range(1, k):
                c = self.tab.item(i + j, self.COL_VALOR)
                c.setText("—")
                c.setForeground(QBrush(COR_CONT))
            i += k

    def _linha_dona(self, linha):
        """Se a linha é continuação de um formato de 2/4 registradores, devolve a linha inicial."""
        if self.bits:
            return linha
        i = 0
        while i < self.d.qtd:
            k = F.n_registradores(self.formatos[i])
            if i <= linha < i + k:
                return i
            i += k
        return linha

    # ── interação ────────────────────────────────────────────────────────────
    def _alias_editado(self, item):
        if item.column() == self.COL_ALIAS:
            self.aliases[item.row()] = item.text()

    def linhas_selecionadas(self):
        linhas = sorted({ix.row() for ix in self.tab.selectedIndexes()})
        return linhas or ([self.tab.currentRow()] if self.tab.currentRow() >= 0 else [])

    def aplica_formato(self, fmt, linhas=None):
        if self.bits:
            return
        for r in (linhas if linhas is not None else self.linhas_selecionadas()):
            self.formatos[r] = fmt
        self._preenche_valores()

    def _duplo_clique(self, linha, col):
        if col == self.COL_VALOR:
            self.escrever_linha(linha)

    def escrever_linha(self, linha):
        if self.d.fc in (2, 4):
            QMessageBox.information(self, "Somente leitura",
                                    f"A função {self.d.fc:02d} é somente leitura.\n"
                                    "Para escrever, use uma janela com FC01 (bobinas) ou FC03 (holding registers).")
            return
        linha = self._linha_dona(linha)
        fmt = self.formatos[linha]
        atual = self.tab.item(linha, self.COL_VALOR).text()
        dlg = DialogoEscritaCelula(self.d.escravo, self.d.fc, self.d.endereco + linha,
                                   rotulo_endereco(self.d, linha), fmt, atual, self)
        if dlg.exec() and dlg.resultado:
            escravo, pdu = dlg.resultado
            self.principal.envia_escrita(escravo, pdu, self.id)

    def _menu_contexto(self, pos):
        m = QMenu(self)
        linha = self.tab.rowAt(pos.y())
        if linha >= 0 and self.d.fc in (1, 3):
            m.addAction("Escrever valor...", lambda: self.escrever_linha(linha))
            m.addSeparator()
        if not self.bits:
            mf = m.addMenu("Formato")
            for g in F.GRUPOS_MENU:
                for nome in g:
                    a = mf.addAction(nome, lambda n=nome: self.aplica_formato(n))
                    a.setCheckable(True)
                    a.setChecked(linha >= 0 and self.formatos[linha] == nome)
                mf.addSeparator()
        m.addAction("Copiar valores", self.copiar)
        m.addSeparator()
        m.addAction("Definição de leitura...", self.editar_definicao)
        m.addAction("Ler agora", lambda: self.com.ler_agora(self.id))
        m.addAction("Zerar contadores", self.zerar)
        m.exec(self.tab.viewport().mapToGlobal(pos))

    def copiar(self):
        linhas = self.linhas_selecionadas() or range(self.tab.rowCount())
        texto = "\n".join("\t".join(self.tab.item(r, c).text() for c in range(3)) for r in linhas)
        QApplication.clipboard().setText(texto)

    def zerar(self):
        self.com.zera_contadores(self.id)
        self._atualiza_cabecalho(0, 0)

    def editar_definicao(self):
        dlg = DialogoDefinicao(self.d, self)
        if dlg.exec():
            nova = dlg.definicao()
            mudou_area = (nova.fc, nova.endereco, nova.qtd) != (self.d.fc, self.d.endereco, self.d.qtd)
            self.d = nova
            if mudou_area:
                self.valores = None
                self.ultimo_ok = None
            self.com.atualiza_leitura(self.id, self.d, zerar=mudou_area)
            self._monta_linhas()
            self._atualiza_cabecalho(0, 0) if mudou_area else None
            self._mostra_status()

    def alterna_pausa(self):
        self.d.ativo = not self.d.ativo
        self.com.atualiza_leitura(self.id, self.d)
        self._atualiza_titulo()
        self._mostra_status()

    def para_dict(self):
        return {"definicao": self.d.to_dict(), "aliases": self.aliases, "formatos": self.formatos}

    def closeEvent(self, e):
        self.com.remove_leitura(self.id)
        super().closeEvent(e)


# ── Janela principal ──────────────────────────────────────────────────────────

class JanelaPrincipal(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(NOME_APP)
        self.resize(1200, 780)
        self.com = Comunicador()
        self.cfg_conexao = {"modo": "rtu", "porta": "", "baud": 9600, "bytesize": 8, "paridade": "N",
                            "stopbits": 1, "host": "192.168.1.10", "porta_tcp": 502,
                            "timeout_ms": 1000, "atraso_ms": 20}
        self.arquivo_ws = None
        self.janelas: dict[int, JanelaLeitura] = {}

        self.mdi = QMdiArea()
        self.mdi.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.mdi.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setCentralWidget(self.mdi)

        self._cria_trafego()
        self._cria_acoes()
        self._cria_menus()
        self._cria_barra()

        self.lb_conexao = QLabel()
        self.statusBar().addPermanentWidget(self.lb_conexao)
        self._mostra_conexao(False, "Desconectado")

        self.com.leitura.connect(self._leitura)
        self.com.escrita.connect(self._escrita)
        self.com.trafego.connect(self._trafego)
        self.com.conexao.connect(self._mostra_conexao)

        if self._carrega(SESSAO, silencioso=True):
            self.statusBar().showMessage("Sessão anterior restaurada · F3 para conectar", 8000)
        else:
            self.nova_leitura()
            self.statusBar().showMessage("F3 conecta · F8 define a leitura · duplo clique no valor para escrever", 8000)

    # ── interface ────────────────────────────────────────────────────────────
    def _acao(self, texto, slot, atalho=None, icone=None, dica=None):
        a = QAction(texto, self)
        if icone is not None:
            a.setIcon(self.style().standardIcon(icone))
        if atalho:
            a.setShortcut(QKeySequence(atalho))
        if dica:
            a.setStatusTip(dica)
            a.setToolTip(f"{dica} ({atalho})" if atalho else dica)
        a.triggered.connect(slot)
        return a

    def _cria_acoes(self):
        S = QStyle.StandardPixmap
        self.ac_nova = self._acao("&Nova leitura", self.nova_leitura, "Ctrl+N", S.SP_FileIcon, "Abre uma nova janela de leitura")
        self.ac_abrir = self._acao("&Abrir workspace...", self.abrir, "Ctrl+O", S.SP_DialogOpenButton, "Abre conexão e janelas salvas")
        self.ac_salvar = self._acao("&Salvar workspace", self.salvar, "Ctrl+S", S.SP_DialogSaveButton, "Salva conexão, janelas, alias e formatos")
        self.ac_salvar_como = self._acao("Salvar workspace &como...", self.salvar_como)
        self.ac_sair = self._acao("Sai&r", self.close)
        self.ac_conectar = self._acao("&Conectar...", self.conectar, "F3", S.SP_MediaPlay, "Configura e abre a conexão")
        self.ac_desconectar = self._acao("&Desconectar", self.desconectar, "F4", S.SP_MediaStop, "Fecha a conexão")
        self.ac_descobrir = self._acao("Descobrir dispositivo &RTU...", self.descobrir, "F6", S.SP_FileDialogContentsView,
                                       "Varre baudrate/paridade/ID até achar o dispositivo")
        self.ac_definicao = self._acao("&Definição de leitura...", self.definicao, "F8", S.SP_FileDialogDetailedView,
                                       "ID, função, endereço, quantidade e taxa da janela ativa")
        self.ac_pausa = self._acao("&Pausar / retomar leitura", self.pausa, "F9", S.SP_MediaPause, "Pausa a janela ativa")
        self.ac_ler = self._acao("&Ler agora", lambda: self._ativa() and self.com.ler_agora(self._ativa().id), "F5",
                                 S.SP_BrowserReload, "Lê a janela ativa imediatamente")
        self.ac_fc = {fc: self._acao(DialogoEscritaManual.TITULOS[fc] + "...", lambda _=False, f=fc: self.escrita_manual(f),
                                     None, None, DialogoEscritaManual.TITULOS[fc]) for fc in (5, 6, 15, 16)}
        self.ac_cascata = self._acao("&Cascata", self.mdi.cascadeSubWindows)
        self.ac_lado = self._acao("&Lado a lado", self.mdi.tileSubWindows)

    def _cria_menus(self):
        mb = self.menuBar()
        m = mb.addMenu("&Arquivo")
        for a in (self.ac_nova, None, self.ac_abrir, self.ac_salvar, self.ac_salvar_como, None, self.ac_sair):
            m.addSeparator() if a is None else m.addAction(a)
        m = mb.addMenu("&Conexão")
        for a in (self.ac_conectar, self.ac_desconectar, None, self.ac_descobrir):
            m.addSeparator() if a is None else m.addAction(a)
        m = mb.addMenu("C&onfiguração")
        for a in (self.ac_definicao, self.ac_pausa, self.ac_ler):
            m.addAction(a)
        m = mb.addMenu("&Funções")
        for a in self.ac_fc.values():
            m.addAction(a)
        m = mb.addMenu("&Exibição")
        self.grupo_fmt = QActionGroup(self)
        for g in F.GRUPOS_MENU:
            for nome in g:
                a = m.addAction(nome, lambda n=nome: self._ativa() and self._ativa().aplica_formato(n))
                self.grupo_fmt.addAction(a)
            m.addSeparator()
        m.addAction(self.dock_trafego.toggleViewAction())
        m = mb.addMenu("&Janela")
        m.addAction(self.ac_cascata)
        m.addAction(self.ac_lado)
        m = mb.addMenu("A&juda")
        m.addAction("Como usar", self.ajuda)

    def _cria_barra(self):
        tb = self.addToolBar("Principal")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        for a in (self.ac_nova, self.ac_abrir, self.ac_salvar, None, self.ac_conectar, self.ac_desconectar,
                  self.ac_descobrir, None, self.ac_definicao, self.ac_ler, self.ac_pausa, None):
            tb.addSeparator() if a is None else tb.addAction(a)
        for fc, a in self.ac_fc.items():
            b = QAction(f"{fc:02d}", self)
            b.setToolTip(a.text().rstrip("."))
            b.triggered.connect(a.trigger)
            tb.addAction(b)
        tb.addSeparator()
        t = self.dock_trafego.toggleViewAction()
        t.setText("Tráfego")
        t.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))
        tb.addAction(t)

    def _cria_trafego(self):
        self.dock_trafego = QDockWidget("Tráfego de comunicação", self)
        self.dock_trafego.setObjectName("trafego")
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(2, 2, 2, 2)
        h = QHBoxLayout()
        self.ck_pausa_trafego = QCheckBox("Pausar")
        bt_limpar = QPushButton("Limpar")
        bt_copiar = QPushButton("Copiar")
        h.addWidget(self.ck_pausa_trafego)
        h.addStretch()
        h.addWidget(bt_copiar)
        h.addWidget(bt_limpar)
        lay.addLayout(h)
        self.tx_trafego = QPlainTextEdit()
        self.tx_trafego.setReadOnly(True)
        self.tx_trafego.setFont(QFont("Consolas", 9))
        self.tx_trafego.setMaximumBlockCount(3000)
        lay.addWidget(self.tx_trafego)
        bt_limpar.clicked.connect(self.tx_trafego.clear)
        bt_copiar.clicked.connect(lambda: QApplication.clipboard().setText(self.tx_trafego.toPlainText()))
        self.dock_trafego.setWidget(w)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.dock_trafego)
        self.dock_trafego.hide()
        self._n_trafego = 0

    # ── janelas ──────────────────────────────────────────────────────────────
    def _ativa(self) -> JanelaLeitura | None:
        sub = self.mdi.activeSubWindow() or (self.mdi.subWindowList()[-1] if self.mdi.subWindowList() else None)
        return sub.widget() if sub else None

    def nova_leitura(self, definicao: Definicao | None = None, aliases=None, formatos=None, mostrar=True):
        if definicao is None:
            atual = self._ativa()
            definicao = Definicao(**atual.d.to_dict()) if atual else Definicao()
        j = JanelaLeitura(self, definicao, aliases, formatos)
        sub = self.mdi.addSubWindow(j)
        sub.setAttribute(Qt.WA_DeleteOnClose)
        sub.resize(440, 380)
        j._atualiza_titulo()
        self.janelas[j.id] = j
        j.destroyed.connect(lambda *_, i=j.id: self._janela_fechada(i))
        if mostrar:
            sub.show()
        return j

    def _janela_fechada(self, i):
        self.janelas.pop(i, None)
        self.com.remove_leitura(i)

    def definicao(self):
        j = self._ativa()
        if j:
            j.editar_definicao()
        else:
            self.nova_leitura()

    def pausa(self):
        j = self._ativa()
        if j:
            j.alterna_pausa()

    # ── conexão ──────────────────────────────────────────────────────────────
    def porta_em_uso(self, porta):
        t = self.com.transporte
        return isinstance(t, TransporteRTU) and t.porta.upper() == porta.upper()

    def conectar(self):
        dlg = DialogoConexao(self.cfg_conexao, self)
        if dlg.exec():
            self.cfg_conexao.update(dlg.config())
            self._abre_conexao()

    def _abre_conexao(self) -> bool:
        c = self.cfg_conexao
        to = c["timeout_ms"] / 1000
        if c["modo"] == "rtu":
            if not c["porta"]:
                QMessageBox.warning(self, "Conexão", "Escolha a porta COM.")
                return False
            t = TransporteRTU(c["porta"], c["baud"], c["paridade"], c["stopbits"], c["bytesize"], to)
        else:
            t = TransporteTCP(c["host"], c["porta_tcp"], to)
        self.com.atraso_ms = c["atraso_ms"]
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.com.conectar(t)
            return True
        except Exception as e:
            self._mostra_conexao(False, "Desconectado")
            QMessageBox.critical(self, "Falha na conexão", f"Não foi possível abrir {t.descricao()}:\n\n{e}")
            return False
        finally:
            QApplication.restoreOverrideCursor()

    def desconectar(self):
        self.com.desconectar()

    def _mostra_conexao(self, ok, texto):
        if ok:
            self.lb_conexao.setText(f"  ● Conectado: {texto}  ")
            self.lb_conexao.setStyleSheet("color: #2E7D32; font-weight: bold")
        else:
            self.lb_conexao.setText(f"  ○ {texto}  ")
            self.lb_conexao.setStyleSheet(f"color: {COR_ERRO}; font-weight: bold")
        self.ac_conectar.setEnabled(not ok)
        self.ac_desconectar.setEnabled(ok)
        for j in self.janelas.values():
            j._mostra_status()

    def descobrir(self):
        dlg = DialogoDescoberta(self.cfg_conexao.get("porta", ""), self)
        dlg.usar.connect(self._usa_descoberta)
        dlg.exec()

    def _usa_descoberta(self, cfg, escravo, fc):
        self.cfg_conexao.update(cfg)
        self.cfg_conexao["modo"] = "rtu"
        if self._abre_conexao():
            self.nova_leitura(Definicao(escravo=escravo, fc=fc, endereco=0, qtd=10))
            self.statusBar().showMessage(
                f"Conectado com a configuração descoberta: ID {escravo}, {cfg['baud']} bps, "
                f"paridade {PARITY_NAME[cfg['paridade']]}, {cfg['stopbits']} stop bit(s)", 10000)

    # ── comunicação ──────────────────────────────────────────────────────────
    def _leitura(self, i, dados):
        j = self.janelas.get(i)
        if j:
            j.recebe(dados)

    def envia_escrita(self, escravo, pdu, id_janela=None):
        if not self.com.conectado:
            QMessageBox.warning(self, "Escrita", "Conecte antes de escrever (F3).")
            return
        self.com.escrever(escravo, pdu, (id_janela, pdu[0]))
        self.statusBar().showMessage(f"Escrevendo (FC{pdu[0]:02d})...")

    def _escrita(self, ctx, erro):
        id_janela, fc = ctx if ctx else (None, 0)
        if erro:
            self.statusBar().showMessage(f"Falha na escrita FC{fc:02d}: {erro}", 10000)
            QMessageBox.warning(self, "Falha na escrita", f"A escrita (função {fc:02d}) não foi aceita:\n\n{erro}")
        else:
            self.statusBar().showMessage(f"Escrita FC{fc:02d} OK", 5000)
            if id_janela in self.janelas:
                self.com.ler_agora(id_janela)
            else:
                for j in self.janelas.values():
                    self.com.ler_agora(j.id)

    def escrita_manual(self, fc):
        j = self._ativa()
        dlg = DialogoEscritaManual(fc, j.d.escravo if j else 1, j.d.endereco if j else 0, self)
        if dlg.exec() and dlg.resultado:
            self.envia_escrita(*dlg.resultado)

    def _trafego(self, direcao, dados, ts):
        if self.ck_pausa_trafego.isChecked() or not self.dock_trafego.isVisible():
            return
        self._n_trafego += 1
        hora = datetime.fromtimestamp(ts).strftime("%H:%M:%S.%f")[:-3]
        hexa = " ".join(f"{b:02X}" for b in dados)
        self.tx_trafego.appendPlainText(f"{self._n_trafego:06d}  {hora}  {direcao}: {hexa}")

    # ── workspace ────────────────────────────────────────────────────────────
    def _estado(self):
        subs = self.mdi.subWindowList()
        return {
            "conexao": self.cfg_conexao,
            "conectado": self.com.conectado,
            "janelas": [dict(s.widget().para_dict(),
                             geometria=[s.x(), s.y(), s.width(), s.height()]) for s in subs],
        }

    def _grava(self, caminho):
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(json.dumps(self._estado(), indent=2, ensure_ascii=False), encoding="utf-8")

    def _carrega(self, caminho, silencioso=False) -> bool:
        try:
            est = json.loads(Path(caminho).read_text(encoding="utf-8"))
        except Exception as e:
            if not silencioso:
                QMessageBox.warning(self, "Abrir workspace", f"Não foi possível abrir:\n{e}")
            return False
        self.com.desconectar()
        for s in self.mdi.subWindowList():
            s.close()
        self.cfg_conexao.update(est.get("conexao", {}))
        for jd in est.get("janelas", []):
            j = self.nova_leitura(Definicao.from_dict(jd.get("definicao", {})), jd.get("aliases"), jd.get("formatos"))
            g = jd.get("geometria")
            if g:
                j.parentWidget().setGeometry(*g)
        if not self.mdi.subWindowList():
            self.nova_leitura()
        if est.get("conectado") and not silencioso:
            self._abre_conexao()
        return True

    def abrir(self):
        PASTA_WS.mkdir(exist_ok=True)
        caminho, _ = QFileDialog.getOpenFileName(self, "Abrir workspace", str(PASTA_WS), "Workspace (*.json)")
        if caminho and self._carrega(caminho):
            self.arquivo_ws = Path(caminho)
            self.setWindowTitle(f"{NOME_APP} — {self.arquivo_ws.stem}")

    def salvar(self):
        if self.arquivo_ws:
            self._grava(self.arquivo_ws)
            self.statusBar().showMessage(f"Salvo em {self.arquivo_ws}", 5000)
        else:
            self.salvar_como()

    def salvar_como(self):
        PASTA_WS.mkdir(exist_ok=True)
        caminho, _ = QFileDialog.getSaveFileName(self, "Salvar workspace", str(PASTA_WS / "teste.json"), "Workspace (*.json)")
        if caminho:
            p = Path(caminho)
            if p.suffix.lower() != ".json":
                p = p.with_name(p.name + ".json")
            self.arquivo_ws = p
            self.salvar()
            self.setWindowTitle(f"{NOME_APP} — {p.stem}")

    def ajuda(self):
        QMessageBox.information(self, "Como usar", (
            "1. F3 — configure a conexão (serial RTU ou TCP) e conecte.\n"
            "   Não sabe a configuração do dispositivo? F6 — Descobrir dispositivo RTU.\n"
            "2. F8 — defina ID, função, endereço inicial, quantidade e taxa da janela.\n"
            "3. Ctrl+N — abre outra janela de leitura (podem rodar várias ao mesmo tempo).\n"
            "4. Clique com o botão direito numa linha para escolher o formato (Float, Long, Hex...).\n"
            "   Formatos de 2/4 registradores ocupam as linhas seguintes (mostradas com —).\n"
            "5. Duplo clique no Valor para escrever (FC05 em bobinas, FC06/16 em registradores).\n"
            "   Duplo clique no Alias para dar nome à linha.\n"
            "6. Menu Funções — escritas avulsas (05, 06, 15, 16).\n"
            "7. Exibição › Tráfego de comunicação — mostra os bytes enviados/recebidos.\n\n"
            "As janelas e a conexão são lembradas ao fechar o programa."))

    def closeEvent(self, e):
        try:
            self._grava(SESSAO)
        except OSError:
            pass
        self.com.parar()
        super().closeEvent(e)
