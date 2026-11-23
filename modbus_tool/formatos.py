"""
Formatos de exibição dos registradores (como no Modbus Poll).

Ordem dos bytes: as letras descrevem como os bytes do valor (A = mais
significativo) estão distribuídos nos registradores, na ordem em que chegam.
Ex.: "CD AB" = palavra menos significativa primeiro (word swap, padrão WAGO).
"""

import struct

# nome -> (registradores, tipo, ordem)
FORMATOS = {
    "Signed":                  (1, "h", "AB"),
    "Unsigned":                (1, "H", "AB"),
    "Hex":                     (1, "hex", "AB"),
    "Binário":                 (1, "bin", "AB"),
    "Long AB CD":              (2, "i", "ABCD"),
    "Long CD AB":              (2, "i", "CDAB"),
    "Long BA DC":              (2, "i", "BADC"),
    "Long DC BA":              (2, "i", "DCBA"),
    "Long sem sinal AB CD":    (2, "I", "ABCD"),
    "Long sem sinal CD AB":    (2, "I", "CDAB"),
    "Float AB CD":             (2, "f", "ABCD"),
    "Float CD AB":             (2, "f", "CDAB"),
    "Float BA DC":             (2, "f", "BADC"),
    "Float DC BA":             (2, "f", "DCBA"),
    "Double AB CD EF GH":      (4, "d", "ABCDEFGH"),
    "Double GH EF CD AB":      (4, "d", "GHEFCDAB"),
}
FORMATO_PADRAO = "Signed"
GRUPOS_MENU = [
    ["Signed", "Unsigned", "Hex", "Binário"],
    ["Long AB CD", "Long CD AB", "Long BA DC", "Long DC BA", "Long sem sinal AB CD", "Long sem sinal CD AB"],
    ["Float AB CD", "Float CD AB", "Float BA DC", "Float DC BA"],
    ["Double AB CD EF GH", "Double GH EF CD AB"],
]


def n_registradores(formato: str) -> int:
    return FORMATOS[formato][0]


def _regs_para_bytes_valor(regs: list[int], ordem: str) -> bytes:
    crus = b"".join(struct.pack(">H", r & 0xFFFF) for r in regs)   # bytes na ordem de chegada
    letras = "".join(sorted(ordem))
    return bytes(crus[ordem.index(c)] for c in letras)            # bytes do valor, A primeiro


def _bytes_valor_para_regs(valor: bytes, ordem: str) -> list[int]:
    letras = "".join(sorted(ordem))
    crus = bytes(valor[letras.index(c)] for c in ordem)
    return [struct.unpack(">H", crus[i:i + 2])[0] for i in range(0, len(crus), 2)]


def formata(regs: list[int], formato: str) -> str:
    """Converte 1..4 registradores no texto exibido."""
    n, tipo, ordem = FORMATOS[formato]
    if tipo == "h":
        return str(struct.unpack(">h", struct.pack(">H", regs[0]))[0])
    if tipo == "H":
        return str(regs[0])
    if tipo == "hex":
        return f"0x{regs[0]:04X}"
    if tipo == "bin":
        b = f"{regs[0]:016b}"
        return " ".join(b[i:i + 4] for i in range(0, 16, 4))
    v = struct.unpack(">" + tipo, _regs_para_bytes_valor(regs[:n], ordem))[0]
    if tipo in ("f", "d"):
        # float32 tem ~7 dígitos significativos; double ~15
        return format(v, ".7g" if tipo == "f" else ".15g")
    return str(v)


def converte_texto(texto: str, formato: str) -> list[int]:
    """Texto digitado -> registradores a escrever (para o formato da linha)."""
    n, tipo, ordem = FORMATOS[formato]
    t = texto.strip().replace(" ", "").replace(",", ".") if tipo != "bin" else texto.replace(" ", "")
    if tipo == "hex":
        v = int(t, 16)
        if not 0 <= v <= 0xFFFF:
            raise ValueError("fora da faixa 0x0000 a 0xFFFF")
        return [v]
    if tipo == "bin":
        v = int(t, 2)
        if not 0 <= v <= 0xFFFF:
            raise ValueError("máximo 16 bits")
        return [v]
    if tipo == "h":
        v = int(t, 0)
        if not -32768 <= v <= 65535:
            raise ValueError("fora da faixa -32768 a 65535")
        return [v & 0xFFFF]
    if tipo == "H":
        v = int(t, 0)
        if not 0 <= v <= 65535:
            raise ValueError("fora da faixa 0 a 65535")
        return [v]
    if tipo in ("i", "I"):
        v = int(t, 0)
        lim = (-2**31, 2**31 - 1) if tipo == "i" else (0, 2**32 - 1)
        if not lim[0] <= v <= lim[1]:
            raise ValueError(f"fora da faixa {lim[0]} a {lim[1]}")
        return _bytes_valor_para_regs(struct.pack(">" + tipo, v), ordem)
    v = float(t)
    return _bytes_valor_para_regs(struct.pack(">" + tipo, v), ordem)
