from flectra import fields, models

class AppointmentCode(models.Model):
    """Codici carica per dichiaranti - semplificato per Flectra"""
    _name = "appointment.code"
    _description = "Appointment Code"
    
    name = fields.Char("Name", required=True)
    code = fields.Char("Code", required=True)
    description = fields.Text("Description")
    
    _sql_constraints = [
        ('code_unique', 'unique(code)', 'Code must be unique!')
    ]