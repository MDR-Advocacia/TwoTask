# app/core/utils.py
import re

def format_cnj(value: str) -> str:
    """
    Formata um número de processo para o padrão CNJ (NNNNNNN-DD.YYYY.J.TR.OOOO).
    Se o valor de entrada já estiver formatado ou não tiver 20 dígitos, 
    ele é retornado sem modificação.
    """
    if not isinstance(value, str):
        return value

    # Remove todos os caracteres que não são dígitos
    cleaned_value = re.sub(r'\D', '', value)

    # Se a string limpa não tiver 20 dígitos, retorna o valor original
    if len(cleaned_value) != 20:
        return value

    # Aplica a máscara do CNJ
    # NNNNNNN-DD.YYYY.J.TR.OOOO
    return (
        f"{cleaned_value[0:7]}-{cleaned_value[7:9]}."
        f"{cleaned_value[9:13]}.{cleaned_value[13:14]}."
        f"{cleaned_value[14:16]}.{cleaned_value[16:20]}"
    )