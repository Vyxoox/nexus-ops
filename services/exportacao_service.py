def valor_exportacao_resultado(resultado, campo):
    valor = resultado.get(campo, None)
    vinculo = str(resultado.get('vinculo', '')).upper()

    campos_so_efetivo = {'matricula'}
    campos_so_terceirizado = {
        'empresa_contratada',
        'numero_contrato',
        'gestor_contrato',
        'lider_tecnico',
        'analista_contratos',
        'representante_fornecedor',
    }

    if vinculo == 'EFETIVO' and campo in campos_so_terceirizado:
        return 'Não se aplica'
    if vinculo == 'TERCEIRIZADO' and campo in campos_so_efetivo:
        return 'Não se aplica'
    if valor is None:
        return ''
    return valor


def limpar_valor_excel(val):
    if val is None:
        return ''

    if isinstance(val, str):
        val = val.strip()
        if val.lower() in ('none', 'nat') or val == '':
            return ''

    return val
