"""
3Di Modbus Tool - testes de variáveis Modbus (RTU serial e TCP), no estilo
do Modbus Poll, com a descoberta automática de dispositivos RTU integrada.

Uso: python ModbusTool.py   (ou dê dois cliques em "3Di Modbus Tool.bat")
"""

import sys

from PySide6.QtWidgets import QApplication

from modbus_tool.janelas import JanelaPrincipal, NOME_APP


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(NOME_APP)
    app.setStyle("Fusion")
    w = JanelaPrincipal()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
