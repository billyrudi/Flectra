from flectra import fields, models

class AccountTax(models.Model):
    _inherit = "account.tax"

    vsc_exclude_operation = fields.Boolean(
        string="Exclude from active / passive operations"
    )
    vsc_exclude_vat = fields.Boolean(string="Exclude from VAT payable / deducted")

class ResPartner(models.Model):
    """Aggiungiamo codice fiscale al partner se non esiste"""
    _inherit = "res.partner"
    
    fiscalcode = fields.Char("Fiscal Code", size=16)