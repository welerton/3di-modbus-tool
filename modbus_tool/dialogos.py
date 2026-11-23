"""Janelas de diálogo: conexão, definição de leitura, escrita e descoberta."""

import threading

from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
    QComboBox, QSpinBox, QLineEdit, QRadioButton, QCheckBox, QPushButton, QLabel, QButtonGroup,
    QPlainTextEdit, QProgressBar, QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QAbstractItemView, QWidget,
)

from . import formatos as F
from .comunicacao import Definicao
from .descoberta import faixa_escravos, varre
from .protocol import BAUDRATES, FUNCOES_LEITURA, PARITY_NAME, lista_portas


def _combo_portas(atual=""):
    cb = QComboBox()
    cb.setEditable(True)
    for p in lista_portas():
        cb.addItem(f"{p.device} — {p.description}", p.device)
    if atual:
        i = cb.findData(atual)
        if i >= 0:
            cb.setCurrentIndex(i)
        else:
            cb.setEditText(atual)
    return cb


def _porta_do_combo(cb: QComboBox) -> str:
    dado = cb.currentData()
    if dado and cb.currentText().startswith(dado):
        return dado
    return cb.currentText().split("—")[0].strip()


# ── Conexão ───────────────────────────────────────────────────────────────────

class DialogoConexao(QDialog):
    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configuração da conexão")
        lay = QVBoxLayout(self)

        modo = QGroupBox("Tipo de conexão")
        hl = QHBoxLayout(modo)
        self.rb_rtu = QRadioButton("Serial (Modbus RTU)")
        self.rb_tcp = QRadioButton("Rede (Modbus TCP/IP)")
        hl.addWidget(self.rb_rtu)
        hl.addWidget(self.rb_tcp)
        lay.addWidget(modo)

        self.gb_rtu = QGroupBox("Porta serial")
        f = QFormLayout(self.gb_rtu)
        linha = QHBoxLayout()
        self.cb_porta = _combo_portas(cfg.get("porta", ""))
        bt = QPushButton("Atualizar")
        bt.clicked.connect(self._atualiza_portas)
        linha.addWidget(self.cb_porta, 1)
        linha.addWidget(bt)
        f.addRow("Porta:", linha)
        self.cb_baud = QComboBox()
        self.cb_baud.setEditable(True)
        self.cb_baud.addItems([str(b) for b in BAUDRATES])
        self.cb_baud.setCurrentText(str(cfg.get("baud", 9600)))
        f.addRow("Baudrate:", self.cb_baud)
        self.cb_bits = QComboBox()
        self.cb_bits.addItems(["8", "7"])
        self.cb_bits.setCurrentText(str(cfg.get("bytesize", 8)))
        f.addRow("Data bits:", self.cb_bits)
        self.cb_par = QComboBox()
        for k, v in PARITY_NAME.items():
            self.cb_par.addItem(v, k)
        self.cb_par.setCurrentIndex(self.cb_par.findData(cfg.get("paridade", "N")))
        f.addRow("Paridade:", self.cb_par)
        self.cb_stop = QComboBox()
        self.cb_stop.addItems(["1", "2"])
        self.cb_stop.setCurrentText(str(cfg.get("stopbits", 1)))
        f.addRow("Stop bits:", self.cb_stop)
        lay.addWidget(self.gb_rtu)

        self.gb_tcp = QGroupBox("Rede")
        f = QFormLayout(self.gb_tcp)
        self.ed_ip = QLineEdit(cfg.get("host", "192.168.1.10"))
        f.addRow("Endereço IP:", self.ed_ip)
        self.sp_porta_tcp = QSpinBox()
        self.sp_porta_tcp.setRange(1, 65535)
        self.sp_porta_tcp.setValue(cfg.get("porta_tcp", 502))
        f.addRow("Porta:", self.sp_porta_tcp)
        lay.addWidget(self.gb_tcp)

        gb = QGroupBox("Tempos")
        f = QFormLayout(gb)
        self.sp_timeout = QSpinBox()
        self.sp_timeout.setRange(50, 30000)
        self.sp_timeout.setSuffix(" ms")
        self.sp_timeout.setValue(cfg.get("timeout_ms", 1000))
        f.addRow("Tempo limite de resposta:", self.sp_timeout)
        self.sp_atraso = QSpinBox()
        self.sp_atraso.setRange(0, 10000)
        self.sp_atraso.setSuffix(" ms")
        self.sp_atraso.setValue(cfg.get("atraso_ms", 20))
        f.addRow("Atraso entre requisições:", self.sp_atraso)
        lay.addWidget(gb)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Conectar")
        bb.button(QDialogButtonBox.Cancel).setText("Cancelar")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

        self.rb_rtu.toggled.connect(self._modo)
        (self.rb_tcp if cfg.get("modo") == "tcp" else self.rb_rtu).setChecked(True)
        self._modo()

    def _atualiza_portas(self):
        atual = _porta_do_combo(self.cb_porta)
        novo = _combo_portas(atual)
        self.cb_porta.clear()
        for i in range(novo.count()):
            self.cb_porta.addItem(novo.itemText(i), novo.itemData(i))
        i = self.cb_porta.findData(atual)
        if i >= 0:
            self.cb_porta.setCurrentIndex(i)

    def _modo(self):
        rtu = self.rb_rtu.isChecked()
        self.gb_rtu.setVisible(rtu)
        self.gb_tcp.setVisible(not rtu)
        self.adjustSize()

    def config(self) -> dict:
        return {
            "modo": "rtu" if self.rb_rtu.isChecked() else "tcp",
            "porta": _porta_do_combo(self.cb_porta),
            "baud": int(self.cb_baud.currentText()),
            "bytesize": int(self.cb_bits.currentText()),
            "paridade": self.cb_par.currentData(),
            "stopbits": int(self.cb_stop.currentText()),
            "host": self.ed_ip.text().strip(),
            "porta_tcp": self.sp_porta_tcp.value(),
            "timeout_ms": self.sp_timeout.value(),
            "atraso_ms": self.sp_atraso.value(),
        }


# ── Definição de leitura ─────────────────────────────────────────────────────

class DialogoDefinicao(QDialog):
    def __init__(self, d: Definicao, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Definição de leitura")
        f = QFormLayout(self)
        self.sp_id = QSpinBox()
        self.sp_id.setRange(0, 255)
        self.sp_id.setValue(d.escravo)
        f.addRow("ID do escravo:", self.sp_id)
        self.cb_fc = QComboBox()
        for fc, nome in FUNCOES_LEITURA.items():
            self.cb_fc.addItem(nome, fc)
        self.cb_fc.setCurrentIndex(self.cb_fc.findData(d.fc))
        f.addRow("Função:", self.cb_fc)
        self.sp_end = QSpinBox()
        self.sp_end.setRange(0, 65535)
        self.sp_end.setValue(d.endereco)
        f.addRow("Endereço inicial (base 0):", self.sp_end)
        self.lb_plc = QLabel()
        self.lb_plc.setStyleSheet("color: gray")
        f.addRow("", self.lb_plc)
        self.sp_qtd = QSpinBox()
        self.sp_qtd.setRange(1, 125)
        self.sp_qtd.setValue(d.qtd)
        f.addRow("Quantidade:", self.sp_qtd)
        self.sp_scan = QSpinBox()
        self.sp_scan.setRange(50, 3600000)
        self.sp_scan.setSuffix(" ms")
        self.sp_scan.setSingleStep(100)
        self.sp_scan.setValue(d.scan_ms)
        f.addRow("Taxa de leitura:", self.sp_scan)
        self.ck_base1 = QCheckBox("Mostrar endereços estilo CLP (base 1: 40001, 30001...)")
        self.ck_base1.setChecked(d.base1)
        f.addRow(self.ck_base1)
        self.ck_ativo = QCheckBox("Leitura ativa")
        self.ck_ativo.setChecked(d.ativo)
        f.addRow(self.ck_ativo)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)
        self.cb_fc.currentIndexChanged.connect(self._limites)
        self.sp_end.valueChanged.connect(self._limites)
        self._limites()

    def _limites(self):
        fc = self.cb_fc.currentData()
        self.sp_qtd.setMaximum(2000 if fc in (1, 2) else 125)
        from .protocol import PREFIXO_PLC
        n = self.sp_end.value() + 1
        dig = PREFIXO_PLC[fc] // 100000
        self.lb_plc.setText(f"= {dig}{n:04d} no endereçamento base 1" if n <= 9999 else f"= {dig}{n:05d} no endereçamento base 1")

    def definicao(self) -> Definicao:
        return Definicao(self.sp_id.value(), self.cb_fc.currentData(), self.sp_end.value(),
                         self.sp_qtd.value(), self.sp_scan.value(), self.ck_base1.isChecked(),
                         self.ck_ativo.isChecked())


# ── Escrita a partir de uma célula ───────────────────────────────────────────

class DialogoEscritaCelula(QDialog):
    """Escreve no endereço clicado: bobina (FC05) ou registrador(es) (FC06/FC16)."""

    def __init__(self, escravo, fc, endereco, rotulo_end, formato, valor_atual, parent=None):
        super().__init__(parent)
        self.fc, self.formato = fc, formato
        bobina = fc == 1
        self.setWindowTitle("Escrever bobina" if bobina else "Escrever registrador")
        f = QFormLayout(self)
        self.sp_id = QSpinBox()
        self.sp_id.setRange(0, 255)
        self.sp_id.setValue(escravo)
        f.addRow("ID do escravo:", self.sp_id)
        f.addRow("Endereço:", QLabel(f"{rotulo_end}   (base 0: {endereco})"))
        self.endereco = endereco
        if bobina:
            self.rb_on = QRadioButton("ON (1)")
            self.rb_off = QRadioButton("OFF (0)")
            (self.rb_off if str(valor_atual) == "1" else self.rb_on).setChecked(True)
            h = QHBoxLayout()
            h.addWidget(self.rb_on)
            h.addWidget(self.rb_off)
            f.addRow("Valor:", h)
        else:
            f.addRow("Formato:", QLabel(formato))
            self.ed_valor = QLineEdit(valor_atual if valor_atual not in ("", None) else "0")
            self.ed_valor.selectAll()
            f.addRow("Novo valor:", self.ed_valor)
            self.ck_fc16 = QCheckBox("Usar função 16 (Write Multiple Registers)")
            multi = F.n_registradores(formato) > 1
            self.ck_fc16.setChecked(multi)
            self.ck_fc16.setEnabled(not multi)
            f.addRow(self.ck_fc16)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Escrever")
        bb.button(QDialogButtonBox.Cancel).setText("Cancelar")
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        f.addRow(bb)
        self.resultado = None

    def _ok(self):
        from .protocol import pdu_escreve_bobina, pdu_escreve_registrador, pdu_escreve_registradores
        if self.fc == 1:
            self.resultado = (self.sp_id.value(), pdu_escreve_bobina(self.endereco, self.rb_on.isChecked()))
        else:
            try:
                regs = F.converte_texto(self.ed_valor.text(), self.formato)
            except ValueError as e:
                QMessageBox.warning(self, "Valor inválido", f"Não foi possível converter o valor:\n{e}")
                return
            if len(regs) == 1 and not self.ck_fc16.isChecked():
                pdu = pdu_escreve_registrador(self.endereco, regs[0])
            else:
                pdu = pdu_escreve_registradores(self.endereco, regs)
            self.resultado = (self.sp_id.value(), pdu)
        self.accept()


# ── Escrita manual (menu Funções) ────────────────────────────────────────────

class DialogoEscritaManual(QDialog):
    TITULOS = {5: "05 Escrever bobina", 6: "06 Escrever registrador",
               15: "15 Escrever várias bobinas", 16: "16 Escrever vários registradores"}

    def __init__(self, fc, escravo=1, endereco=0, parent=None):
        super().__init__(parent)
        self.fc = fc
        self.setWindowTitle(self.TITULOS[fc])
        f = QFormLayout(self)
        self.sp_id = QSpinBox()
        self.sp_id.setRange(0, 255)
        self.sp_id.setValue(escravo)
        f.addRow("ID do escravo:", self.sp_id)
        self.sp_end = QSpinBox()
        self.sp_end.setRange(0, 65535)
        self.sp_end.setValue(endereco)
        f.addRow("Endereço (base 0):", self.sp_end)
        if fc == 5:
            self.cb_val = QComboBox()
            self.cb_val.addItems(["ON (1)", "OFF (0)"])
            f.addRow("Valor:", self.cb_val)
        else:
            self.cb_fmt = QComboBox()
            if fc == 15:
                self.cb_fmt.addItem("Bits (0/1)")
                self.cb_fmt.setEnabled(False)
            else:
                nomes = [n for g in F.GRUPOS_MENU for n in g]
                if fc == 6:
                    nomes = [n for n in nomes if F.n_registradores(n) == 1]
                self.cb_fmt.addItems(nomes)
            f.addRow("Formato:", self.cb_fmt)
            self.ed = QLineEdit("1" if fc == 6 else ("1; 0; 1" if fc == 15 else "1; 2; 3"))
            f.addRow("Valor:" if fc == 6 else "Valores (separados por ;):", self.ed)
            if fc != 6:
                dica = QLabel("Ex.: 10; 20; 30  ·  floats: 1.5; 2.25")
                dica.setStyleSheet("color: gray")
                f.addRow("", dica)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Escrever")
        bb.button(QDialogButtonBox.Cancel).setText("Cancelar")
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        f.addRow(bb)
        self.resultado = None

    def _ok(self):
        from .protocol import (pdu_escreve_bobina, pdu_escreve_bobinas, pdu_escreve_registrador,
                               pdu_escreve_registradores)
        end = self.sp_end.value()
        try:
            if self.fc == 5:
                pdu = pdu_escreve_bobina(end, self.cb_val.currentIndex() == 0)
            elif self.fc == 15:
                bits = [p.strip() for p in self.ed.text().replace(",", ";").split(";") if p.strip()]
                if any(b not in ("0", "1") for b in bits) or not bits:
                    raise ValueError("use apenas 0 e 1")
                pdu = pdu_escreve_bobinas(end, [b == "1" for b in bits])
            elif self.fc == 6:
                pdu = pdu_escreve_registrador(end, F.converte_texto(self.ed.text(), self.cb_fmt.currentText())[0])
            else:
                regs = []
                for p in self.ed.text().split(";"):
                    if p.strip():
                        regs += F.converte_texto(p, self.cb_fmt.currentText())
                if not regs or len(regs) > 123:
                    raise ValueError("entre 1 e 123 registradores")
                pdu = pdu_escreve_registradores(end, regs)
        except ValueError as e:
            QMessageBox.warning(self, "Valor inválido", str(e))
            return
        self.resultado = (self.sp_id.value(), pdu)
        self.accept()


# ── Descoberta ───────────────────────────────────────────────────────────────

class _SinaisVarredura(QObject):
    log = Signal(str)
    progresso = Signal(int, int)
    fim = Signal(object)


class DialogoDescoberta(QDialog):
    """Varre baudrate/paridade/stop bits/ID até achar o dispositivo RTU."""

    usar = Signal(dict, int, int)   # (config de conexão, ID, função)

    def __init__(self, porta_atual="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Descobrir dispositivo Modbus RTU")
        self.resize(820, 640)
        lay = QVBoxLayout(self)

        gb = QGroupBox("O que testar")
        g = QGridLayout(gb)
        g.addWidget(QLabel("Porta:"), 0, 0)
        self.cb_porta = _combo_portas(porta_atual)
        g.addWidget(self.cb_porta, 0, 1, 1, 3)

        g.addWidget(QLabel("Baudrates:"), 1, 0)
        hb = QHBoxLayout()
        self.ck_baud = {}
        for b in [9600, 19200, 4800, 38400, 57600, 115200, 2400, 1200]:
            ck = QCheckBox(str(b))
            ck.setChecked(True)
            self.ck_baud[b] = ck
            hb.addWidget(ck)
        g.addLayout(hb, 1, 1, 1, 3)

        g.addWidget(QLabel("Paridade:"), 2, 0)
        hp = QHBoxLayout()
        self.ck_par = {}
        for k, v in PARITY_NAME.items():
            ck = QCheckBox(v)
            ck.setChecked(True)
            self.ck_par[k] = ck
            hp.addWidget(ck)
        g.addLayout(hp, 2, 1)
        g.addWidget(QLabel("Stop bits:"), 2, 2)
        hs = QHBoxLayout()
        self.ck_stop = {}
        for s in (1, 2):
            ck = QCheckBox(str(s))
            ck.setChecked(True)
            self.ck_stop[s] = ck
            hs.addWidget(ck)
        g.addLayout(hs, 2, 3)

        g.addWidget(QLabel("IDs dos escravos:"), 3, 0)
        self.ed_ids = QLineEdit("1-32")
        self.ed_ids.setToolTip("Ex.: 1-32  ·  1,2,5  ·  1-247 (varredura completa, mais lenta)")
        g.addWidget(self.ed_ids, 3, 1)
        g.addWidget(QLabel("Funções:"), 3, 2)
        hf = QHBoxLayout()
        self.ck_fc4 = QCheckBox("04 Input")
        self.ck_fc3 = QCheckBox("03 Holding")
        self.ck_fc4.setChecked(True)
        self.ck_fc3.setChecked(True)
        hf.addWidget(self.ck_fc4)
        hf.addWidget(self.ck_fc3)
        g.addLayout(hf, 3, 3)

        g.addWidget(QLabel("Endereço / quantidade:"), 4, 0)
        he = QHBoxLayout()
        self.sp_end = QSpinBox()
        self.sp_end.setRange(0, 65535)
        self.sp_qtd = QSpinBox()
        self.sp_qtd.setRange(1, 125)
        self.sp_qtd.setValue(1)
        he.addWidget(self.sp_end)
        he.addWidget(self.sp_qtd)
        g.addLayout(he, 4, 1)
        g.addWidget(QLabel("Tempo por tentativa:"), 4, 2)
        self.sp_to = QSpinBox()
        self.sp_to.setRange(30, 5000)
        self.sp_to.setValue(150)
        self.sp_to.setSuffix(" ms")
        g.addWidget(self.sp_to, 4, 3)
        g.addWidget(QLabel("Parar após encontrar:"), 5, 0)
        self.sp_parar = QSpinBox()
        self.sp_parar.setRange(0, 247)
        self.sp_parar.setValue(1)
        self.sp_parar.setSpecialValueText("não parar (varrer tudo)")
        g.addWidget(self.sp_parar, 5, 1)
        self.lb_estimativa = QLabel()
        self.lb_estimativa.setStyleSheet("color: gray")
        g.addWidget(self.lb_estimativa, 5, 2, 1, 2)
        lay.addWidget(gb)

        hb = QHBoxLayout()
        self.bt_iniciar = QPushButton("▶  Iniciar varredura")
        self.bt_cancelar = QPushButton("■  Cancelar")
        self.bt_cancelar.setEnabled(False)
        self.barra = QProgressBar()
        hb.addWidget(self.bt_iniciar)
        hb.addWidget(self.bt_cancelar)
        hb.addWidget(self.barra, 1)
        lay.addLayout(hb)

        self.tab = QTableWidget(0, 7)
        self.tab.setHorizontalHeaderLabels(["Resultado", "Porta", "Baudrate", "Paridade", "Stop bits", "ID", "Função / detalhe"])
        self.tab.horizontalHeader().setSectionResizeMode(6, QHeaderView.Stretch)
        self.tab.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tab.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tab.verticalHeader().setVisible(False)
        self.tab.setMaximumHeight(170)
        lay.addWidget(QLabel("Dispositivos encontrados (duplo clique para usar):"))
        lay.addWidget(self.tab)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFont("Consolas", 9))
        lay.addWidget(self.log, 1)

        hb2 = QHBoxLayout()
        hb2.addStretch()
        self.bt_usar = QPushButton("Usar a configuração selecionada")
        self.bt_usar.setEnabled(False)
        bt_fechar = QPushButton("Fechar")
        hb2.addWidget(self.bt_usar)
        hb2.addWidget(bt_fechar)
        lay.addLayout(hb2)

        self.sinais = _SinaisVarredura()
        self.sinais.log.connect(self.log.appendPlainText)
        self.sinais.progresso.connect(self._progresso)
        self.sinais.fim.connect(self._fim)
        self.bt_iniciar.clicked.connect(self._iniciar)
        self.bt_cancelar.clicked.connect(self._cancelar)
        self.bt_usar.clicked.connect(self._usar)
        self.tab.itemDoubleClicked.connect(lambda *_: self._usar())
        self.tab.itemSelectionChanged.connect(lambda: self.bt_usar.setEnabled(bool(self.tab.selectedItems())))
        bt_fechar.clicked.connect(self.close)
        for w in list(self.ck_baud.values()) + list(self.ck_par.values()) + list(self.ck_stop.values()) + [self.ck_fc3, self.ck_fc4]:
            w.toggled.connect(self._estima)
        self.ed_ids.textChanged.connect(self._estima)
        self.sp_to.valueChanged.connect(self._estima)
        self._cancelado = False
        self._thread = None
        self._achados = []
        self._estima()

    def _params(self):
        bauds = [b for b, ck in self.ck_baud.items() if ck.isChecked()]
        pars = [p for p, ck in self.ck_par.items() if ck.isChecked()]
        stops = [s for s, ck in self.ck_stop.items() if ck.isChecked()]
        fcs = ([4] if self.ck_fc4.isChecked() else []) + ([3] if self.ck_fc3.isChecked() else [])
        ids = faixa_escravos(self.ed_ids.text())
        return bauds, pars, stops, ids, fcs

    def _estima(self):
        try:
            b, p, s, ids, fcs = self._params()
            n = len(b) * len(p) * len(s) * len(ids) * len(fcs)
            seg = n * self.sp_to.value() / 1000
            self.lb_estimativa.setText(f"{n} tentativas · no máximo ~{seg / 60:.1f} min" if seg >= 60 else f"{n} tentativas · no máximo ~{seg:.0f} s")
        except ValueError as e:
            self.lb_estimativa.setText(f"IDs inválidos: {e}")

    def _iniciar(self):
        try:
            bauds, pars, stops, ids, fcs = self._params()
        except ValueError as e:
            QMessageBox.warning(self, "IDs inválidos", str(e))
            return
        if not (bauds and pars and stops and ids and fcs):
            QMessageBox.warning(self, "Varredura", "Marque pelo menos uma opção em cada grupo.")
            return
        porta = _porta_do_combo(self.cb_porta)
        if not porta:
            QMessageBox.warning(self, "Varredura", "Escolha a porta COM.")
            return
        if self.parent() and getattr(self.parent(), "porta_em_uso", lambda p: False)(porta):
            if QMessageBox.question(self, "Porta em uso",
                                    f"{porta} está conectada nas leituras. Desconectar para fazer a varredura?") != QMessageBox.Yes:
                return
            self.parent().desconectar()
        self.tab.setRowCount(0)
        self.log.clear()
        self._achados = []
        self._cancelado = False
        self.bt_iniciar.setEnabled(False)
        self.bt_cancelar.setEnabled(True)
        self.barra.setValue(0)
        kw = dict(porta=porta, baudrates=bauds, paridades=pars, stopbits=stops, escravos=ids, funcoes=fcs,
                  endereco=self.sp_end.value(), qtd=self.sp_qtd.value(), timeout=self.sp_to.value() / 1000,
                  parar_apos=self.sp_parar.value(), cancelado=lambda: self._cancelado,
                  ao_log=self.sinais.log.emit, ao_progresso=self.sinais.progresso.emit)
        self._thread = threading.Thread(target=lambda: self.sinais.fim.emit(varre(**kw)), daemon=True)
        self._thread.start()

    def _cancelar(self):
        self._cancelado = True
        self.bt_cancelar.setEnabled(False)

    def _progresso(self, feito, total):
        self.barra.setMaximum(total)
        self.barra.setValue(feito)

    def _fim(self, achados):
        self.bt_iniciar.setEnabled(True)
        self.bt_cancelar.setEnabled(False)
        self._achados = achados
        for a in achados:
            r = self.tab.rowCount()
            self.tab.insertRow(r)
            vals = ["✔ dados" if a.status == "ok" else "⚠ exceção", a.porta, str(a.baud), PARITY_NAME[a.paridade],
                    str(a.stopbits), str(a.escravo), f"FC{a.fc:02d} · {a.detalhe}"]
            for c, v in enumerate(vals):
                self.tab.setItem(r, c, QTableWidgetItem(v))
        if achados:
            self.tab.selectRow(0)
        else:
            self.log.appendPlainText("\nNenhuma resposta. Confira A/B do RS485, o terminador e a porta COM; "
                                     "tente IDs 1-247 ou outro endereço.")

    def _usar(self):
        r = self.tab.currentRow()
        if r < 0 or r >= len(self._achados):
            return
        a = self._achados[r]
        cfg = {"modo": "rtu", "porta": a.porta, "baud": a.baud, "bytesize": 8, "paridade": a.paridade,
               "stopbits": a.stopbits}
        self.usar.emit(cfg, a.escravo, a.fc)
        self.close()

    def closeEvent(self, e):
        self._cancelado = True
        super().closeEvent(e)
