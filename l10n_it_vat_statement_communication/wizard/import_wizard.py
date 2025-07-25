from flectra import _, api, fields, models
from flectra.exceptions import UserError


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
    
    # NUOVO: Opzioni avanzate
    force_overwrite = fields.Boolean("Overwrite existing VP data", default=True, 
                                   help="If unchecked, will only create new VP records")
    exclude_zero_amounts = fields.Boolean("Exclude periods with zero amounts", default=False,
                                        help="Don't create VP records if all amounts are zero")

    def action_import_data(self):
        """ESEGUE L'IMPORTAZIONE PER I PERIODI SELEZIONATI - VERSIONE MIGLIORATA"""
        
        if not self.comunicazione_id:
            raise UserError(_("Communication not found!"))
            
        if not self.comunicazione_id.company_id:
            raise UserError(_("Please select a company in the communication!"))
        
        # Verifica che ci siano fatture nel database
        invoice_count = self.env['account.move'].search_count([
            ('company_id', '=', self.comunicazione_id.company_id.id),
            ('state', '=', 'posted')
        ])
        
        if invoice_count == 0:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Warning!'),
                    'message': _('No posted invoices found for company %s. Please post some invoices first.') % self.comunicazione_id.company_id.name,
                    'type': 'warning',
                }
            }
        
        periods_to_create = []
        
        if self.create_all_periods:
            # Crea tutti i periodi dell'anno
            if self.period_type == "month":
                periods_to_create = [
                    {'period_type': 'month', 'month': i, 'quarter': False} 
                    for i in range(1, 13)
                ]
            else:
                periods_to_create = [
                    {'period_type': 'quarter', 'quarter': i, 'month': False} 
                    for i in range(1, 5)
                ]
        else:
            # Usa le selezioni manuali
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
        if self.force_overwrite:
            existing_vp = self.comunicazione_id.quadri_vp_ids
            if existing_vp:
                existing_vp.unlink()
        
        created_count = 0
        imported_count = 0
        skipped_count = 0
        errors = []
        
        # Crea e importa dati per ogni periodo
        for period_data in periods_to_create:
            try:
                # Controlla se esiste già
                if not self.force_overwrite:
                    existing = self.comunicazione_id.quadri_vp_ids.filtered(
                        lambda vp: vp.period_type == period_data['period_type'] and
                                  vp.month == period_data['month'] and
                                  vp.quarter == period_data['quarter']
                    )
                    if existing:
                        skipped_count += 1
                        continue
                
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
                vp_record.action_import_from_invoices_single()
                
                # Controlla se escludere periodi con importi zero
                if self.exclude_zero_amounts:
                    if (vp_record.imponibile_operazioni_attive == 0 and 
                        vp_record.imponibile_operazioni_passive == 0 and
                        vp_record.iva_esigibile == 0 and 
                        vp_record.iva_detratta == 0):
                        vp_record.unlink()
                        created_count -= 1
                        skipped_count += 1
                        continue
                
                imported_count += 1
                
            except Exception as e:
                error_msg = _("Error importing period %s: %s") % (
                    f"{period_data['month'] or period_data['quarter']}", str(e)
                )
                errors.append(error_msg)
                
                # Log dell'errore
                self.comunicazione_id.message_post(body=error_msg)
        
        # Messaggio di completamento
        message_parts = [
            _('✅ Import process completed!'),
            _('📊 Created: %s periods') % created_count,
            _('📈 Imported data: %s periods') % imported_count,
        ]
        
        if skipped_count > 0:
            message_parts.append(_('⏭️ Skipped: %s periods') % skipped_count)
            
        if errors:
            message_parts.append(_('❌ Errors: %s') % len(errors))
        
        message_parts.append(_('💾 Total invoices in database: %s') % invoice_count)
        
        # Log generale
        self.comunicazione_id.message_post(
            body=_("""
            <div class="alert alert-info">
                <h4>🚀 Bulk Import Summary</h4>
                <ul>
                    <li>Company: %s</li>
                    <li>Year: %s</li>
                    <li>Period type: %s</li>
                    <li>Periods created: %s</li>
                    <li>Data imported: %s</li>
                    <li>Skipped: %s</li>
                    <li>Errors: %s</li>
                </ul>
            </div>
            """) % (
                self.comunicazione_id.company_id.name,
                self.year,
                self.period_type,
                created_count,
                imported_count,
                skipped_count,
                len(errors)
            )
        )
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Import Completed!'),
                'message': '\n'.join(message_parts),
                'type': 'success' if not errors else 'warning',
            }
        }