# 3Di Modbus Tool

Ferramenta para testar variáveis Modbus (RTU serial e TCP/IP), com interface no estilo do Modbus Poll e descoberta automática da configuração de dispositivos RTU.

## Como usar

Dê dois cliques em **`3Di Modbus Tool.bat`** (instala `pyserial` e `PySide6` na primeira execução) ou rode:

```
pip install -r requirements.txt
python ModbusTool.py
```

| Tecla | Ação |
|---|---|
| F3 / F4 | Conectar / desconectar (serial RTU ou TCP/IP) |
| F6 | Descobrir dispositivo RTU (varre baudrate, paridade, stop bits e ID) |
| F8 | Definição da janela ativa: ID, função (01–04), endereço, quantidade, taxa |
| F5 / F9 | Ler agora / pausar a janela ativa |
| Ctrl+N | Nova janela de leitura |
| Ctrl+S / Ctrl+O | Salvar / abrir workspace |

- **Formatos por linha** (botão direito): Signed, Unsigned, Hex, Binário, Long, Float e Double nas ordens AB CD, CD AB, BA DC e DC BA.
- **Escrita:** duplo clique no valor (FC05 em bobinas, FC06/FC16 em registradores) ou menu *Funções* (05, 06, 15, 16).
- **Tráfego de comunicação:** bytes Tx/Rx com horário (menu *Exibição*).
- A conexão e as janelas são lembradas ao fechar.

## Estrutura

- `modbus_tool/protocol.py` — Modbus RTU/TCP direto sobre pyserial/socket (CRC, quadros, exceções)
- `modbus_tool/formatos.py` — conversão de registradores para os formatos de exibição/escrita
- `modbus_tool/descoberta.py` — varredura de configuração RTU
- `modbus_tool/comunicacao.py` — thread de comunicação (leituras periódicas e escritas)
- `modbus_tool/janelas.py`, `modbus_tool/dialogos.py` — interface (PySide6)
