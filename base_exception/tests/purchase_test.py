# Copyright 2016 Akretion Mourad EL HADJ MIMOUNE
# Copyright 2020 Hibou Corp.
# Copyright 2025 Raumschmiede GmbH
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
from odoo import api, fields, models


class ExceptionRule(models.Model):
    _inherit = "exception.rule"
    _name = "exception.rule"

    method = fields.Selection(
        selection_add=[("exception_method_no_zip", "Purchase exception no zip")]
    )
    model = fields.Selection(
        selection_add=[
            ("test.purchase", "Purchase Test"),
            ("test.purchase.line.reverse.parent", "Purchase Test Line Reverse Parent"),
            ("test.purchase.line.reverse.self", "Purchase Test Line Self Reverse"),
        ],
        ondelete={
            "test.purchase": "cascade",
            "test.purchase.line.reverse.parent": "cascade",
            "test.purchase.line.reverse.self": "cascade",
        },
    )
    test_purchase_ids = fields.Many2many("test.purchase")
    test_purchase_line_reverse_self_ids = fields.Many2many(
        "test.purchase.line.reverse.self",
    )


class PurchaseTest(models.Model):
    _inherit = "base.exception"
    _name = "test.purchase"
    _description = "Test Model"

    name = fields.Char(required=True)
    user_id = fields.Many2one("res.users", string="Responsible")
    state = fields.Selection(
        [
            ("draft", "New"),
            ("cancel", "Cancelled"),
            ("purchase", "Purchase"),
            ("to approve", "To approve"),
            ("done", "Done"),
        ],
        string="Status",
        readonly=True,
        default="draft",
    )
    active = fields.Boolean(default=True)
    partner_id = fields.Many2one("res.partner", string="Partner")
    line_ids = fields.One2many("test.purchase.line.reverse.parent", "lead_id")
    line_reverse_self_ids = fields.One2many(
        "test.purchase.line.reverse.self", "lead_id"
    )
    amount_total = fields.Float(compute="_compute_amount_total", store=True)

    @api.depends("line_ids")
    def _compute_amount_total(self):
        for record in self:
            for line in record.line_ids:
                record.amount_total += line.amount * line.qty

    @api.constrains("ignore_exception", "line_ids", "state")
    def test_purchase_check_exception(self):
        orders = self.filtered(lambda s: s.state == "purchase")
        if orders:
            orders._check_exception()

    def button_approve(self, force=False):
        self.write({"state": "to approve"})
        return {}

    def button_draft(self):
        self.write({"state": "draft"})
        return {}

    def button_confirm(self):
        self.write({"state": "purchase"})
        return True

    def button_cancel(self):
        self.write({"state": "cancel"})

    def _reverse_field(self):
        return "test_purchase_ids"

    def _get_sub_exception_field_names(self):
        # With line_reverse_self_ids returned here but its model does not use
        # test.purchase as _reverse_field and _get_main_record, the underlying
        # detected exceptions are not in exception_ids of test.purchase but in
        # its exception summary
        return ["line_ids", "line_reverse_self_ids"]

    def exception_method_no_zip(self):
        records_fail = self.browse()
        for rec in self:
            if not rec.partner_id.zip:
                records_fail += rec
        return records_fail


class LineTestReverseParent(models.Model):
    _inherit = "base.exception"
    _name = "test.purchase.line.reverse.parent"
    _description = "Test Model Line Parent Reverse"

    name = fields.Char()
    lead_id = fields.Many2one("test.purchase", ondelete="cascade")
    qty = fields.Float()
    amount = fields.Float()

    def _reverse_field(self):
        return "test_purchase_ids"

    def _get_main_records(self):
        return self.lead_id

    def _detect_exceptions(self, rule):
        records = super()._detect_exceptions(rule)
        (self - records).exception_ids = [(3, rule.id)]
        records.exception_ids = [(4, rule.id)]
        return records.lead_id


class LineTestReverseSelf(models.Model):
    _inherit = "base.exception"
    _name = "test.purchase.line.reverse.self"
    _description = "Test Model Line Self Reverse"

    name = fields.Char()
    lead_id = fields.Many2one("test.purchase", ondelete="cascade")
    qty = fields.Float()
    amount = fields.Float()

    def _reverse_field(self):
        return "test_purchase_line_reverse_self_ids"
