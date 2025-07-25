
UPDATED_MANIFEST = """{
    "name": "ITA - Comunicazione liquidazione IVA (Flectra) - COMPLETA",
    "summary": "Comunicazione liquidazione IVA con importazione automatica dalle fatture - Compatibile Flectra 3.0",
    "version": "3.0.2.0.0",
    "category": "Accounting",
    "author": "Versione Completa per Flectra 3.0",
    "website": "https://github.com/OCA/l10n-italy",
    "license": "AGPL-3",
    "depends": [
        "account",
        "base",
        "mail",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/appointment_code_data.xml",
        "views/comunicazione_liquidazione.xml",
        "views/config.xml", 
        "views/account.xml",
        "wizard/export_file_view.xml",
        "wizard/import_wizard_view.xml",
    ],
    "installable": True,
}"""