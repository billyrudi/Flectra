from flectra import _, api, fields, models
from flectra.exceptions import UserError
from datetime import date
from dateutil.relativedelta import relativedelta


class ComunicazioneLiquidazioneVp(models.Model):
    _name = "comunicazione.liquidazione.vp"
    _description = "VAT statement communication - VP table"

    # IMPORTANTE: Campo comunicazione_id DEVE essere il primo campo definito
    comunicazione_id = fields.Many2one(
        "comunicazione.liquidazione", string="Communication", required=True, ondelete='cascade'
    )

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

    period_type = fields.Selection(
        [("month", "Monthly"), ("quarter", "Quarterly")],
        string="Period type",
        default="month",
    )
    month = fields.Integer(default=False)
    quarter = fields.Integer(default=False)
    subcontracting = fields.Boolean(string="Subcontracting")
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
        """IMPORTA DATI DAL PERIODO SPECIFICO"""
        if not self.comunicazione_id or not self.comunicazione_id.year:
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
        """IMPORTA I DATI DALLE FATTURE DEL PERIODO SPECIFICATO - VERSIONE MIGLIORATA"""
        
        if not self.comunicazione_id or not self.comunicazione_id.company_id:
            raise UserError(_("Communication or company not found!"))
            
        company_id = self.comunicazione_id.company_id.id
        
        # Debug info
        self.env.cr.execute("SELECT COUNT(*) FROM account_move WHERE company_id = %s", (company_id,))
        total_moves = self.env.cr.fetchone()[0]
        
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
        
        # === CALCOLO OPERAZIONI ATTIVE (FATTURE VENDITA) ===
        active_operations_total = 0
        vat_due_total = 0
        
        for invoice in customer_invoices:
            # Imponibile (esclusa IVA)
            base_amount = invoice.amount_untaxed or 0
            tax_amount = invoice.amount_tax or 0
            
            if invoice.move_type == 'out_invoice':
                active_operations_total += base_amount
                vat_due_total += tax_amount
            else:  # note di credito
                active_operations_total -= base_amount
                vat_due_total -= tax_amount
        
        # === CALCOLO OPERAZIONI PASSIVE (FATTURE ACQUISTO) ===
        passive_operations_total = 0
        vat_deductible_total = 0
        
        for invoice in vendor_invoices:
            base_amount = invoice.amount_untaxed or 0
            tax_amount = invoice.amount_tax or 0
            
            # Filtro per tasse escluse (se i campi esistono)
            exclude_operation = False
            exclude_vat = False
            
            # Controlla se ci sono tasse da escludere
            for line in invoice.invoice_line_ids:
                for tax in line.tax_ids:
                    if hasattr(tax, 'vsc_exclude_operation') and tax.vsc_exclude_operation:
                        exclude_operation = True
                    if hasattr(tax, 'vsc_exclude_vat') and tax.vsc_exclude_vat:
                        exclude_vat = True
            
            if not exclude_operation:
                if invoice.move_type == 'in_invoice':
                    passive_operations_total += base_amount
                    if not exclude_vat:
                        vat_deductible_total += tax_amount
                else:  # note di credito
                    passive_operations_total -= base_amount
                    if not exclude_vat:
                        vat_deductible_total -= tax_amount
        
        # === AGGIORNA I CAMPI ===
        vals = {
            'imponibile_operazioni_attive': active_operations_total,
            'imponibile_operazioni_passive': passive_operations_total,
            'iva_esigibile': vat_due_total,
            'iva_detratta': vat_deductible_total,
        }
        
        self.write(vals)
        
        # === LOG DETTAGLIATO ===
        message = _("""
        <div class="alert alert-success">
            <h4>✅ Automatic Import Completed</h4>
            <table class="table table-sm">
                <tr><td><b>Period:</b></td><td>%s to %s</td></tr>
                <tr><td><b>Active Operations:</b></td><td>€ %s</td></tr>
                <tr><td><b>Passive Operations:</b></td><td>€ %s</td></tr>
                <tr><td><b>VAT Due (Customer invoices):</b></td><td>€ %s</td></tr>
                <tr><td><b>VAT Deductible (Vendor invoices):</b></td><td>€ %s</td></tr>
                <tr><td><b>Customer invoices processed:</b></td><td>%s</td></tr>
                <tr><td><b>Vendor invoices processed:</b></td><td>%s</td></tr>
                <tr><td><b>Total invoices in DB:</b></td><td>%s</td></tr>
            </table>
        </div>
        """) % (
            date_start, date_end,
            f"{active_operations_total:,.2f}",
            f"{passive_operations_total:,.2f}",
            f"{vat_due_total:,.2f}", 
            f"{vat_deductible_total:,.2f}",
            len(customer_invoices),
            len(vendor_invoices),
            total_moves
        )
        
        self.comunicazione_id.message_post(body=message)