from app.services.classifier.taxonomy import repair_classification, validate_classification


def _assert_repaired(raw_category, raw_subcategory, expected_category, expected_subcategory):
    category, subcategory = repair_classification(raw_category, raw_subcategory)

    assert (category, subcategory) == (expected_category, expected_subcategory)
    assert validate_classification(category, subcategory)


def test_repair_classification_accepts_batch_aliases_seen_in_errors():
    _assert_repaired(
        "Senten\u00e7a",
        "Senten\u00e7a de Extin\u00e7\u00e3o sem Resolu\u00e7\u00e3o",
        "Senten\u00e7a",
        "Senten\u00e7a de Extin\u00e7\u00e3o sem Resolu\u00e7\u00e3o",
    )
    _assert_repaired(
        "2\u00b0 Grau - C\u00edvel",
        "Acord\u00e3o - N\u00e3o Definido",
        "2\u00b0 Grau - C\u00edvel",
        "Acord\u00e3o N\u00e3o Definido",
    )
    _assert_repaired(
        "Embargos de Declara\u00e7\u00e3o",
        "-",
        "Embargos de Declara\u00e7\u00e3o",
        "Embargos de Declara\u00e7\u00e3o - Para An\u00e1lise",
    )
    _assert_repaired(
        "Cita\u00e7\u00e3o",
        "Cita\u00e7\u00e3o para Apresenta\u00e7\u00e3o de Documentos",
        "Cita\u00e7\u00e3o",
        "Cita\u00e7\u00e3o para Apresenta\u00e7\u00e3o de Documentos",
    )
    _assert_repaired(
        "Recurso Inominado - Contrarraz\u00f5es",
        "Abertura de Prazo",
        "Recurso Inominado",
        "Contrarraz\u00f5es",
    )
    _assert_repaired(
        "Saneamento e Organiza\u00e7\u00e3o do Processo",
        "-",
        "Saneamento e Organiza\u00e7\u00e3o do Processo",
        "-",
    )
    _assert_repaired(
        "Manifesta\u00e7\u00e3o",
        "Sobre Laudo",
        "Manifesta\u00e7\u00e3o das Partes",
        "-",
    )
