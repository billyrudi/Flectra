from lxml import etree
from flectra import _, api, fields, models
from flectra.exceptions import ValidationError, UserError
from datetime import datetime, date
from dateutil.relativedelta import relativedelta

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
        domain = [("identificativo", "=", self.identificativo)]
        dichiarazioni = self.search(domain)
        if len(dichiarazioni) > 1:
            raise ValidationError(
                _("Communication with identifier {} already exists").format(
                    self.identificativo
                )
            )

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
            dich.name = name

    def _get_identificativo(self):
        dichiarazioni = self.search([])
        if dichiarazioni:
            return len(dichiarazioni) + 1
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
    taxpayer_fiscalcode = fields.Char()
    declarant_different = fields.Boolean(
        string="Declarant different from taxpayer", default=True
    )
    declarant_fiscalcode = fields.Char()
    declarant_fiscalcode_company = fields.Char(string="Fiscalcode company")
    codice_carica_id = fields.Many2one("appointment.code", string="Role code")
    declarant_sign = fields.Boolean(string="Declarant sign", default=True)

    delegate_fiscalcode = fields.Char()
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
            self.taxpayer_fiscalcode = self.company_id.partner_id.fiscalcode

    def action_import_from_invoices(self):
        """NUOVA FUNZIONE: Importa automaticamente dalle fatture"""
        if not self.year:
            raise UserError(_("Please specify the year first!"))
        
        # Creiamo quadri VP automaticamente per tutti i mesi/trimestri dell'anno
        return {
            'name': _('Import from Invoices'),
            'type': 'ir.actions.act_window',
            'res_model': 'comunicazione.liquidazione.import.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_comunicazione_id': self.id,
                'default_year': self.year,
            }
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
        
        # Numero Modulo
        NumeroModulo = etree.SubElement(xModulo, etree.QName(NS_IV, "NumeroModulo"))
        NumeroModulo.text = str(self._context.get("nr_modulo", 1))

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


class ComunicazioneLiquidazioneVp(models.Model):
    _name = "comunicazione.liquidazione.vp"
    _description = "VAT statement communication - VP table"

    @api.depends("iva_esigibile", "iva_detratta")
    def _compute_VP6_iva_dovuta_credito(self):
        for quadro in self:
            quadro.iva_dovuta_debito = 0
            quadro.iva_dovuta_credito = 0
            if quadro.iva_esigibile >= quadro.iva_detratta:
                quadro.iva_dovuta_debito = quadro.iva_esigibile - quadro.iva_detratta
            else:
                quadro.iva_dovuta_credito = quadro.iva_detratta - quadro.iva_esigibile

    @api.depends(
        "iva_dovuta_debito",
        "iva_dovuta_credito", 
        "debito_periodo_precedente",
        "credito_periodo_precedente",
        "credito_anno_precedente",
        "versamento_auto_UE",
        "crediti_imposta",
        "interessi_dovuti",
        "accounto_dovuto",
    )
    def _compute_VP14_iva_da_versare_credito(self):
        for quadro in self:
            quadro.iva_da_versare = 0
            quadro.iva_a_credito = 0
            
            if quadro.period_type == "quarter" and quadro.quarter == 5:
                continue
                
            debito = (
                quadro.iva_dovuta_debito
                + quadro.debito_periodo_precedente
                + quadro.interessi_dovuti
            )
            credito = (
                quadro.iva_dovuta_credito
                + quadro.credito_periodo_precedente
                + quadro.credito_anno_precedente
                + quadro.versamento_auto_UE
                + quadro.crediti_imposta
                + quadro.accounto_dovuto
            )
            
            if debito >= credito:
                quadro.iva_da_versare = debito - credito
            else:
                quadro.iva_a_credito = credito - debito

    comunicazione_id = fields.Many2one(
        "comunicazione.liquidazione", string="Communication", readonly=True
    )
    period_type = fields.Selection(
        [("month", "Monthly"), ("quarter", "Quarterly")],
        string="Period type",
        default="month",
    )
    month = fields.Integer(default=False)
    quarter = fields.Integer(default=False)
    subcontracting = fields.Boolean()
    exceptional_events = fields.Selection(
        [("1", "Code 1"), ("9", "Code 9")], string="Exceptional events"
    )

    # Campi dati IVA
    imponibile_operazioni_attive = fields.Float(string="Active operations total (without VAT)")
    imponibile_operazioni_passive = fields.Float(string="Passive operations total (without VAT)")
    iva_esigibile = fields.Float(string="Due VAT")
    iva_detratta = fields.Float(string="Deducted VAT")
    
    iva_dovuta_debito = fields.Float(
        string="Debit VAT", compute="_compute_VP6_iva_dovuta_credito", store=True
    )
    iva_dovuta_credito = fields.Float(
        string="Credit due VAT", compute="_compute_VP6_iva_dovuta_credito", store=True
    )
    
    debito_periodo_precedente = fields.Float(string="Previous period debit")
    credito_periodo_precedente = fields.Float(string="Previous period credit")
    credito_anno_precedente = fields.Float(string="Previous year credit")
    versamento_auto_UE = fields.Float(string="Auto UE payment")
    crediti_imposta = fields.Float(string="Tax credits")
    interessi_dovuti = fields.Float(string="Due interests for quarterly statements")
    accounto_dovuto = fields.Float(string="Down payment due")
    
    metodo_calcolo_acconto = fields.Selection(
        [
            ("1", "Storico"),
            ("2", "Previsionale"), 
            ("3", "Analitico - effettivo"),
            ("4", '"4" (soggetti particolari)'),
        ],
        string="Down payment computation method",
    )
    
    iva_da_versare = fields.Float(
        string="VAT to pay", compute="_compute_VP14_iva_da_versare_credito", store=True
    )
    iva_a_credito = fields.Float(
        string="Credit VAT", compute="_compute_VP14_iva_da_versare_credito", store=True
    )

    def _reset_values(self):
        for quadro in self:
            quadro.imponibile_operazioni_attive = 0
            quadro.imponibile_operazioni_passive = 0
            quadro.iva_esigibile = 0
            quadro.iva_detratta = 0
            quadro.debito_periodo_precedente = 0
            quadro.credito_periodo_precedente = 0
            quadro.credito_anno_precedente = 0
            quadro.versamento_auto_UE = 0
            quadro.crediti_imposta = 0
            quadro.interessi_dovuti = 0
            quadro.accounto_dovuto = 0
            quadro.metodo_calcolo_acconto = False

    def action_import_from_invoices_single(self):
        """NUOVA FUNZIONE: Importa dati dal periodo specifico"""
        if not self.comunicazione_id.year:
            raise UserError(_("Please specify the year in the communication first!"))
        
        if self.period_type == "month" and not self.month:
            raise UserError(_("Please specify the month!"))
        elif self.period_type == "quarter" and not self.quarter:
            raise UserError(_("Please specify the quarter!"))
        
        # Calcola date di inizio e fine periodo
        year = self.comunicazione_id.year
        
        if self.period_type == "month":
            date_start = date(year, self.month, 1)
            date_end = date_start + relativedelta(months=1) - relativedelta(days=1)
        else:  # quarter
            if self.quarter == 1:
                date_start = date(year, 1, 1)
                date_end = date(year, 3, 31)
            elif self.quarter == 2:
                date_start = date(year, 4, 1)
                date_end = date(year, 6, 30)
            elif self.quarter == 3:
                date_start = date(year, 7, 1)
                date_end = date(year, 9, 30)
            else:  # quarter 4
                date_start = date(year, 10, 1)
                date_end = date(year, 12, 31)

        # Reset valori
        self._reset_values()
        
        # Importa dalle fatture
        self._import_invoice_data(date_start, date_end)
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Import completed!'),
                'message': _('Data imported successfully from invoices for period %s to %s') % (date_start, date_end),
                'type': 'success',
            }
        }

    def _import_invoice_data(self, date_start, date_end):
        """Importa i dati dalle fatture del periodo specificato"""
        company_id = self.comunicazione_id.company_id.id
        
        # FATTURE DI VENDITA (IVA ESIGIBILE + OPERAZIONI ATTIVE)
        customer_invoices = self.env['account.move'].search([
            ('move_type', 'in', ['out_invoice', 'out_refund']),
            ('state', '=', 'posted'),
            ('company_id', '=', company_id),
            ('invoice_date', '>=', date_start),
            ('invoice_date', '<=', date_end),
        ])
        
        # FATTURE DI ACQUISTO (IVA DETRAIBILE + OPERAZIONI PASSIVE)
        vendor_invoices = self.env['account.move'].search([
            ('move_type', 'in', ['in_invoice', 'in_refund']),
            ('state', '=', 'posted'),
            ('company_id', '=', company_id),
            ('invoice_date', '>=', date_start),
            ('invoice_date', '<=', date_end),
        ])
        
        # Calcola totali operazioni attive (fatture vendita)
        active_operations_total = 0
        vat_due_total = 0
        
        for invoice in customer_invoices:
            # Imponibile (esclusa IVA)
            if invoice.move_type == 'out_invoice':
                active_operations_total += invoice.amount_untaxed
                vat_due_total += invoice.amount_tax
            else:  # note di credito
                active_operations_total -= invoice.amount_untaxed
                vat_due_total -= invoice.amount_tax
        
        # Calcola totali operazioni passive (fatture acquisto)
        passive_operations_total = 0
        vat_deductible_total = 0
        
        for invoice in vendor_invoices:
            # Filtra solo IVA detraibile (escludi indetraibili)
            deductible_tax = 0
            for tax_line in invoice.line_ids.filtered(lambda l: l.tax_line_id):
                tax = tax_line.tax_line_id
                # Se la tassa non è esclusa dalle operazioni e dall'IVA
                if not tax.vsc_exclude_operation and not tax.vsc_exclude_vat:
                    if invoice.move_type == 'in_invoice':
                        passive_operations_total += abs(invoice.amount_untaxed)
                        deductible_tax += abs(tax_line.balance)
                    else:  # note di credito
                        passive_operations_total -= abs(invoice.amount_untaxed)
                        deductible_tax -= abs(tax_line.balance)
            
            vat_deductible_total += deductible_tax
        
        # Aggiorna i campi
        self.imponibile_operazioni_attive = active_operations_total
        self.imponibile_operazioni_passive = passive_operations_total
        self.iva_esigibile = vat_due_total
        self.iva_detratta = vat_deductible_total
        
        # Log dell'importazione
        self.comunicazione_id.message_post(
            body=_("""
            <b>Automatic import completed for period %s - %s:</b><br/>
            • Active operations: €%s<br/>
            • Passive operations: €%s<br/>
            • VAT due: €%s<br/>
            • VAT deductible: €%s<br/>
            • Customer invoices processed: %s<br/>
            • Vendor invoices processed: %s
            """) % (
                date_start, date_end,
                f"{active_operations_total:,.2f}",
                f"{passive_operations_total:,.2f}",
                f"{vat_due_total:,.2f}", 
                f"{vat_deductible_total:,.2f}",
                len(customer_invoices),
                len(vendor_invoices)
            )
        )


# ===== WIZARD PER IMPORTAZIONE AUTOMATICA =====

class ComunicazioneLiquidazioneImportWizard(models.TransientModel):
    _name = "comunicazione.liquidazione.import.wizard"
    _description = "Import VAT data from invoices wizard"

    comunicazione_id = fields.Many2one("comunicazione.liquidazione", required=True)
    year = fields.Integer(required=True)
    period_type = fields.Selection([
        ("month", "Monthly"),
        ("quarter", "Quarterly")
    ], default="month", required=True)
    
    # Selezione periodi
    create_all_periods = fields.Boolean("Create all periods of the year", default=True)
    
    # Selezione mesi (se mensile)
    month_1 = fields.Boolean("January", default=True)
    month_2 = fields.Boolean("February", default=True)
    month_3 = fields.Boolean("March", default=True)
    month_4 = fields.Boolean("April", default=True)
    month_5 = fields.Boolean("May", default=True)
    month_6 = fields.Boolean("June", default=True)
    month_7 = fields.Boolean("July", default=True)
    month_8 = fields.Boolean("August", default=True)
    month_9 = fields.Boolean("September", default=True)
    month_10 = fields.Boolean("October", default=True)
    month_11 = fields.Boolean("November", default=True)
    month_12 = fields.Boolean("December", default=True)
    
    # Selezione trimestri (se trimestrale)
    quarter_1 = fields.Boolean("Q1 (Jan-Mar)", default=True)
    quarter_2 = fields.Boolean("Q2 (Apr-Jun)", default=True)
    quarter_3 = fields.Boolean("Q3 (Jul-Sep)", default=True)
    quarter_4 = fields.Boolean("Q4 (Oct-Dec)", default=True)

    def action_import_data(self):
        """Esegue l'importazione per i periodi selezionati"""
        periods_to_create = []
        
        if self.period_type == "month":
            months = [
                (1, self.month_1), (2, self.month_2), (3, self.month_3),
                (4, self.month_4), (5, self.month_5), (6, self.month_6),
                (7, self.month_7), (8, self.month_8), (9, self.month_9),
                (10, self.month_10), (11, self.month_11), (12, self.month_12)
            ]
            
            for month_num, selected in months:
                if selected:
                    periods_to_create.append({
                        'period_type': 'month',
                        'month': month_num,
                        'quarter': False
                    })
        
        else:  # quarterly
            quarters = [
                (1, self.quarter_1), (2, self.quarter_2), 
                (3, self.quarter_3), (4, self.quarter_4)
            ]
            
            for quarter_num, selected in quarters:
                if selected:
                    periods_to_create.append({
                        'period_type': 'quarter',
                        'quarter': quarter_num,
                        'month': False
                    })
        
        if not periods_to_create:
            raise UserError(_("Please select at least one period!"))
        
        # Rimuovi periodi esistenti se richiesto
        existing_vp = self.comunicazione_id.quadri_vp_ids
        if existing_vp:
            existing_vp.unlink()
        
        created_count = 0
        imported_count = 0
        
        # Crea e importa dati per ogni periodo
        for period_data in periods_to_create:
            # Crea il quadro VP
            vp_vals = {
                'comunicazione_id': self.comunicazione_id.id,
                'period_type': period_data['period_type'],
                'month': period_data['month'],
                'quarter': period_data['quarter'],
            }
            
            vp_record = self.env['comunicazione.liquidazione.vp'].create(vp_vals)
            created_count += 1
            
            # Importa automaticamente i dati
            try:
                vp_record.action_import_from_invoices_single()
                imported_count += 1
            except Exception as e:
                # Log dell'errore ma continua con gli altri periodi
                self.comunicazione_id.message_post(
                    body=_("Error importing data for period %s: %s") % (
                        f"{period_data['month'] or period_data['quarter']}", str(e)
                    )
                )
        
        # Messaggio di completamento
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Import Completed!'),
                'message': _('Created %s periods and imported data for %s periods successfully!') % (created_count, imported_count),
                'type': 'success',
            }
        }

