from lxml import etree
from flectra import _, api, fields, models
from flectra.exceptions import ValidationError, UserError

NS_IV = "urn:www.agenziaentrate.gov.it:specificheTecniche:sco:ivp"
NS_XSI = "http://www.w3.org/2001/XMLSchema-instance"
NS_LOCATION = "urn:www.agenziaentrate.gov.it:specificheTecniche:sco:ivp"
NS_MAP = {
    "iv": NS_IV,
    "xsi": NS_XSI,
}
etree.register_namespace("vi", NS_IV)

class ComunicazioneLiquidazione(models.Model):
    _inherit = ["mail.thread"]
    _name = "comunicazione.liquidazione"
    _description = "VAT statement communication"

    @api.model
    def _default_company(self):
        company_id = self._context.get("company_id", self.env.company.id)
        return company_id

    @api.constrains("identificativo")
    def _check_identificativo(self):
        for record in self:
            domain = [("identificativo", "=", record.identificativo), ("id", "!=", record.id)]
            dichiarazioni = self.search(domain)
            if dichiarazioni:
                raise ValidationError(
                    _("Communication with identifier {} already exists").format(
                        record.identificativo
                    )
                )

    @api.depends("quadri_vp_ids", "quadri_vp_ids.period_type", "quadri_vp_ids.month", "quadri_vp_ids.quarter", "year")
    def _compute_name(self):
        for dich in self:
            name = ""
            for quadro in dich.quadri_vp_ids:
                if not name:
                    period_type = ""
                    if quadro.period_type == "month":
                        period_type = _("month")
                    else:
                        period_type = _("quarter")
                    name += f"{str(dich.year)} {period_type}"
                if quadro.period_type == "month":
                    name += f", {str(quadro.month)}"
                else:
                    name += f", {str(quadro.quarter)}"
            dich.name = name or f"Communication {dich.year or 'No Year'}"

    @api.depends("quadri_vp_ids")
    def _compute_vp_count(self):
        for record in self:
            record.vp_count = len(record.quadri_vp_ids)

    def _get_identificativo(self):
        dichiarazioni = self.search([])
        if dichiarazioni:
            max_id = max(dichiarazioni.mapped('identificativo'))
            return max_id + 1
        else:
            return 1

    company_id = fields.Many2one(
        "res.company", string="Company", required=True, default=_default_company
    )
    identificativo = fields.Integer(string="Identifier", default=_get_identificativo)
    name = fields.Char(compute="_compute_name", store=True)
    year = fields.Integer(required=True)
    last_month = fields.Integer(string="Last month")
    liquidazione_del_gruppo = fields.Boolean(string="Group's statement")
    taxpayer_vat = fields.Char(string="Vat", required=True)
    controller_vat = fields.Char(string="Controller TIN")
    taxpayer_fiscalcode = fields.Char(string="Taxpayer Fiscalcode")
    declarant_different = fields.Boolean(
        string="Declarant different from taxpayer", default=True
    )
    declarant_fiscalcode = fields.Char(string="Declarant Fiscalcode")
    declarant_fiscalcode_company = fields.Char(string="Fiscalcode company")
    codice_carica_id = fields.Many2one("appointment.code", string="Role code")
    declarant_sign = fields.Boolean(string="Declarant sign", default=True)

    delegate_fiscalcode = fields.Char(string="Delegate Fiscalcode")
    delegate_commitment = fields.Selection(
        [
            ("1", "Communication prepared by taxpayer"),
            ("2", "Communication prepared by sender"),
        ],
        string="Commitment",
    )
    delegate_sign = fields.Boolean(string="Delegate sign")
    date_commitment = fields.Date(string="Date commitment")
    quadri_vp_ids = fields.One2many(
        "comunicazione.liquidazione.vp", "comunicazione_id", string="VP tables"
    )
    iva_da_versare = fields.Float(string="VAT to pay", readonly=True)
    iva_a_credito = fields.Float(string="Credit VAT", readonly=True)
    
    # NUOVO: Campo conteggio per la vista
    vp_count = fields.Integer(string="VP Count", compute="_compute_vp_count")

    @api.model_create_multi
    def create(self, vals_list):
        communications = super().create(vals_list)
        for communication in communications:
            communication._validate()
        return communications

    def write(self, vals):
        super().write(vals)
        for communication in self:
            communication._validate()
        return True

    @api.onchange("company_id")
    def onchange_company_id(self):
        if self.company_id:
            if self.company_id.partner_id.vat:
                self.taxpayer_vat = self.company_id.partner_id.vat[2:]
            else:
                self.taxpayer_vat = ""
            if hasattr(self.company_id.partner_id, 'fiscalcode'):
                self.taxpayer_fiscalcode = self.company_id.partner_id.fiscalcode

    def action_import_from_invoices(self):
        """IMPORTA AUTOMATICAMENTE DALLE FATTURE"""
        if not self.year:
            raise UserError(_("Please specify the year first!"))
        
        if not self.company_id:
            raise UserError(_("Please select a company first!"))
        
        # Verifica che ci siano fatture
        invoice_count = self.env['account.move'].search_count([
            ('company_id', '=', self.company_id.id),
            ('state', '=', 'posted')
        ])
        
        if invoice_count == 0:
            raise UserError(_(
                "No posted invoices found for company %s. "
                "Please post some invoices first before importing VAT data."
            ) % self.company_id.name)
        
        # Apri il wizard di importazione
        return {
            'name': _('Import VAT Data from Invoices'),
            'type': 'ir.actions.act_window',
            'res_model': 'comunicazione.liquidazione.import.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_comunicazione_id': self.id,
                'default_year': self.year,
            }
        }

    def action_view_vp_summary(self):
        """VISUALIZZA RIASSUNTO VP"""
        return {
            'name': _('VP Tables Summary'),
            'type': 'ir.actions.act_window',
            'res_model': 'comunicazione.liquidazione.vp',
            'view_mode': 'tree,form',
            'domain': [('comunicazione_id', '=', self.id)],
            'context': {'default_comunicazione_id': self.id}
        }

    def get_export_xml(self):
        """Esporta XML secondo specifiche Agenzia Entrate"""
        self._validate()
        x1_Fornitura = self._export_xml_get_fornitura()
        x1_1_Intestazione = self._export_xml_get_intestazione()

        attrs = {"identificativo": str(self.identificativo).zfill(5)}
        x1_2_Comunicazione = etree.Element(etree.QName(NS_IV, "Comunicazione"), attrs)
        x1_2_1_Frontespizio = self._export_xml_get_frontespizio()
        x1_2_Comunicazione.append(x1_2_1_Frontespizio)

        x1_2_2_DatiContabili = etree.Element(etree.QName(NS_IV, "DatiContabili"))
        nr_modulo = 0
        for quadro in self.quadri_vp_ids:
            nr_modulo += 1
            modulo = self.with_context(nr_modulo=nr_modulo)._export_xml_get_dati_modulo(
                quadro
            )
            x1_2_2_DatiContabili.append(modulo)
        x1_2_Comunicazione.append(x1_2_2_DatiContabili)
        
        # Composizione struttura xml
        x1_Fornitura.append(x1_1_Intestazione)
        x1_Fornitura.append(x1_2_Comunicazione)

        xml_string = etree.tostring(
            x1_Fornitura, encoding="utf8", method="xml", pretty_print=True
        )
        return xml_string

    def _validate(self):
        """Controllo congruità dati della comunicazione"""
        self.ensure_one()
        # Validazioni base
        if not self.year:
            raise ValidationError(_("Year required"))

        if not self.taxpayer_fiscalcode or len(self.taxpayer_fiscalcode) not in [11, 16]:
            raise ValidationError(
                _("Taxpayer Fiscalcode is required. Length must be 11 or 16 chars")
            )

        if (
            self.taxpayer_fiscalcode
            and len(self.taxpayer_fiscalcode) == 11
            and not self.declarant_fiscalcode
        ):
            raise ValidationError(
                _("Declarant Fiscalcode is required for company fiscal codes")
            )

        # Altre validazioni...
        if self.liquidazione_del_gruppo:
            if self.controller_vat:
                raise ValidationError(
                    _("For group's statement, controller's TIN must be empty")
                )
            if len(self.taxpayer_fiscalcode) == 16:
                raise ValidationError(
                    _("Group's statement not valid for 16 character fiscal codes")
                )

        return True

    def _export_xml_get_fornitura(self):
        return etree.Element(etree.QName(NS_IV, "Fornitura"), nsmap=NS_MAP)

    def _export_xml_get_intestazione(self):
        x1_1_Intestazione = etree.Element(etree.QName(NS_IV, "Intestazione"))
        
        # Codice Fornitura
        x1_1_1_CodiceFornitura = etree.SubElement(
            x1_1_Intestazione, etree.QName(NS_IV, "CodiceFornitura")
        )
        code = self.company_id.vsc_supply_code
        x1_1_1_CodiceFornitura.text = code
        
        # Codice Fiscale Dichiarante
        if self.declarant_fiscalcode:
            x1_1_2_CodiceFiscaleDichiarante = etree.SubElement(
                x1_1_Intestazione, etree.QName(NS_IV, "CodiceFiscaleDichiarante")
            )
            x1_1_2_CodiceFiscaleDichiarante.text = str(self.declarant_fiscalcode)
        
        # Codice Carica
        if self.codice_carica_id:
            x1_1_3_CodiceCarica = etree.SubElement(
                x1_1_Intestazione, etree.QName(NS_IV, "CodiceCarica")
            )
            x1_1_3_CodiceCarica.text = str(self.codice_carica_id.code)
        
        return x1_1_Intestazione

    def _export_xml_get_frontespizio(self):
        x1_2_1_Frontespizio = etree.Element(etree.QName(NS_IV, "Frontespizio"))
        
        # Codice Fiscale
        x1_2_1_1_CodiceFiscale = etree.SubElement(
            x1_2_1_Frontespizio, etree.QName(NS_IV, "CodiceFiscale")
        )
        x1_2_1_1_CodiceFiscale.text = str(self.taxpayer_fiscalcode) if self.taxpayer_fiscalcode else ""
        
        # Anno Imposta
        x1_2_1_2_AnnoImposta = etree.SubElement(
            x1_2_1_Frontespizio, etree.QName(NS_IV, "AnnoImposta")
        )
        x1_2_1_2_AnnoImposta.text = str(self.year)
        
        # Partita IVA
        x1_2_1_3_PartitaIVA = etree.SubElement(
            x1_2_1_Frontespizio, etree.QName(NS_IV, "PartitaIVA")
        )
        x1_2_1_3_PartitaIVA.text = self.taxpayer_vat
        
        # Altri campi del frontespizio...
        if self.controller_vat:
            x1_2_1_4_PIVAControllante = etree.SubElement(
                x1_2_1_Frontespizio, etree.QName(NS_IV, "PIVAControllante")
            )
            x1_2_1_4_PIVAControllante.text = self.controller_vat

        if self.last_month:
            x1_2_1_5_UltimoMese = etree.SubElement(
                x1_2_1_Frontespizio, etree.QName(NS_IV, "UltimoMese")
            )
            x1_2_1_5_UltimoMese.text = str(self.last_month)

        # Liquidazione Gruppo
        x1_2_1_6_LiquidazioneGruppo = etree.SubElement(
            x1_2_1_Frontespizio, etree.QName(NS_IV, "LiquidazioneGruppo")
        )
        x1_2_1_6_LiquidazioneGruppo.text = "1" if self.liquidazione_del_gruppo else "0"

        # Altri campi opzionali...
        if self.declarant_fiscalcode:
            x1_2_1_7_CFDichiarante = etree.SubElement(
                x1_2_1_Frontespizio, etree.QName(NS_IV, "CFDichiarante")
            )
            x1_2_1_7_CFDichiarante.text = self.declarant_fiscalcode

        # FirmaDichiarazione
        x1_2_1_10_FirmaDichiarazione = etree.SubElement(
            x1_2_1_Frontespizio, etree.QName(NS_IV, "FirmaDichiarazione")
        )
        x1_2_1_10_FirmaDichiarazione.text = "1" if self.declarant_sign else "0"

        return x1_2_1_Frontespizio

    def _export_xml_get_dati_modulo(self, quadro):
        """Genera sezione Modulo XML"""
        xModulo = etree.Element(etree.QName(NS_IV, "Modulo"))
        
        if quadro.period_type == "month":
            Mese = etree.SubElement(xModulo, etree.QName(NS_IV, "Mese"))
            Mese.text = str(quadro.month)
        else:
            Trimestre = etree.SubElement(xModulo, etree.QName(NS_IV, "Trimestre"))
            Trimestre.text = str(quadro.quarter)

        # Campi obbligatori
        if not self.liquidazione_del_gruppo:
            TotaleOperazioniAttive = etree.SubElement(
                xModulo, etree.QName(NS_IV, "TotaleOperazioniAttive")
            )
            TotaleOperazioniAttive.text = f"{quadro.imponibile_operazioni_attive:.2f}".replace(".", ",")
            
            TotaleOperazioniPassive = etree.SubElement(
                xModulo, etree.QName(NS_IV, "TotaleOperazioniPassive")
            )
            TotaleOperazioniPassive.text = f"{quadro.imponibile_operazioni_passive:.2f}".replace(".", ",")

        # IVA
        IvaEsigibile = etree.SubElement(xModulo, etree.QName(NS_IV, "IvaEsigibile"))
        IvaEsigibile.text = f"{quadro.iva_esigibile:.2f}".replace(".", ",")
        
        IvaDetratta = etree.SubElement(xModulo, etree.QName(NS_IV, "IvaDetratta"))
        IvaDetratta.text = f"{quadro.iva_detratta:.2f}".replace(".", ",")

        # Altri campi del modulo...
        if quadro.iva_dovuta_debito:
            IvaDovuta = etree.SubElement(xModulo, etree.QName(NS_IV, "IvaDovuta"))
            IvaDovuta.text = f"{quadro.iva_dovuta_debito:.2f}".replace(".", ",")

        if quadro.iva_dovuta_credito:
            IvaCredito = etree.SubElement(xModulo, etree.QName(NS_IV, "IvaCredito"))
            IvaCredito.text = f"{quadro.iva_dovuta_credito:.2f}".replace(".", ",")

        return xModulo