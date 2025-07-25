# -*- coding: utf-8 -*-
{
    "name": "ITA - Comunicazione liquidazione IVA",
    "summary": "Comunicazione liquidazione IVA ed export file XML",
    "version": "3.0.1.0.0",
    "category": "Accounting/Localizations",
    "author": "Openforce di Camilli Alessandro",
    "website": "https://github.com/OCA/l10n-italy",
    "license": "AGPL-3",
    "depends": [
        "account",
        "base",
        "mail",
    ],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/appointment_code_data.xml",
        "views/comunicazione_liquidazione.xml",
        "views/config.xml", 
        "views/account.xml",
        "wizard/export_file_view.xml",
        "wizard/import_wizard_view.xml",
    ],
    "installable": True,
    "auto_install": False,
    "application": False,
}