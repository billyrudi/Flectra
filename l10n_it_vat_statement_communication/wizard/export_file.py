import base64
from flectra import _, fields, models
from flectra.exceptions import UserError

class ComunicazioneLiquidazioneExportFile(models.TransientModel):
    _name = "comunicazione.liquidazione.export.file"
    _description = "Export VAT statement communication XML file"

    file_export = fields.Binary("File", readonly=True)
    name = fields.Char("File Name", readonly=True, default="liquidazione.xml")

    def export(self):
        comunicazione_ids = self._context.get("active_ids")
        if not comunicazione_ids:
            raise UserError(_("No communication selected"))
        if len(comunicazione_ids) > 1:
            raise UserError(_("You can export only 1 communication at a time"))

        for wizard in self:
            for comunicazione in self.env["comunicazione.liquidazione"].browse(
                comunicazione_ids
            ):
                out = base64.encodebytes(comunicazione.get_export_xml())
                wizard.sudo().file_export = out
                wizard.name = "{}_LI_{}.xml".format(
                    comunicazione.declarant_fiscalcode,
                    str(comunicazione.identificativo).rjust(5, "0"),
                )
            view_id = self.env.ref(
                "l10n_it_vat_statement_communication.wizard_liquidazione_export_file_exit"
            ).id

            return {
                "view_id": [view_id],
                "view_mode": "form",
                "res_model": "comunicazione.liquidazione.export.file",
                "res_id": wizard.id,
                "type": "ir.actions.act_window",
                "target": "new",
            }
