# Copyright 2011 Raphaël Valyi, Renato Lima, Guewen Baconnier, Sodexis
# Copyright 2017 Akretion (http://www.akretion.com)
# Copyright 2025 Raumschmiede GmbH
# Mourad EL HADJ MIMOUNE <mourad.elhadj.mimoune@akretion.com>
# Copyright 2020 Hibou Corp.
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

import html
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.osv import expression
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)


class ExceptionRule(models.Model):
    _name = "exception.rule"
    _description = "Exception Rule"
    _order = "active desc, sequence asc"

    name = fields.Char("Exception Name", required=True, translate=True)
    description = fields.Text(
        "Description",
        translate=True,
        help="You can use placeholders here. The placeholder syntax depends on "
        "the description template type.\n"
        "Examples:\n\n"
        "Jinja: 'Product with SKU ${record.default_code} has no costs set'\n\n"
        "Variables: 'Product with SKU {var1} has no costs set'.\n"
        "In code: 'var1 = record.default_code'",
    )
    description_template_type = fields.Selection(
        [
            ("plain", "Text"),
            ("jinja", "Jinja"),
            ("variables", "Variables"),
        ],
        default="plain",
        required=True,
        help="Define how the text in the description field shall be handled.\n"
        "Text: Use the description as it is without formatting it\n"
        "Jinja: You can use custom ${object.field} syntax to define dynamic "
        "values in the description\n"
        "Variables: You can use custom {var1} syntax in the description. In the page "
        "Description Code you have to set all variables: var1 = object.field",
    )
    description_variables_code = fields.Text(
        "Description Variables",
        help="For each variable enclosed in curly brackets in the description you must"
        " assign a value to a variable in the code with the same name.\n"
        "Variables available: object, exception_rule\n"
        "Example:\n"
        "Description: 'Product with SKU {sku} contains invalid characters: {chars}\n"
        "Code:\n"
        "sku = object.default_code\n"
        "invalid_chars = ['!', '$', '?']\n"
        "chars = ', '.join([c for c in invalid_chars if c in object.name])",
    )
    sequence = fields.Integer(
        string="Sequence", help="Gives the sequence order when applying the test"
    )
    model = fields.Selection(selection=[], string="Apply on", required=True)

    exception_type = fields.Selection(
        selection=[
            ("by_domain", "By domain"),
            ("by_py_code", "By python code"),
            ("by_method", "By method"),
        ],
        string="Exception Type",
        required=True,
        default="by_py_code",
        help="By python code: allow to define any arbitrary check\n"
        "By domain: limited to a selection by an odoo domain:\n"
        "           performance can be better when exceptions"
        "           are evaluated with several records\n"
        "By method: allow to select an existing check method",
    )
    domain = fields.Char("Domain")
    method = fields.Selection(selection=[], string="Method", readonly=True)
    active = fields.Boolean("Active", default=True)
    code = fields.Text(
        "Python Code",
        help="Python code executed to check if the exception apply or "
        "not. Use failed = True to block the exception",
    )
    is_blocking = fields.Boolean(
        string="Is blocking",
        help="When checked the exception can not be ignored",
    )

    @api.constrains("exception_type", "domain", "code", "model")
    def check_exception_type_consistency(self):
        for rule in self:
            if (
                (rule.exception_type == "by_py_code" and not rule.code)
                or (rule.exception_type == "by_domain" and not rule.domain)
                or (rule.exception_type == "by_method" and not rule.method)
            ):
                raise ValidationError(
                    _(
                        "There is a problem of configuration, python code, "
                        "domain or method is missing to match the exception "
                        "type."
                    )
                )

    def _get_domain(self):
        """override me to customize domains according exceptions cases"""
        self.ensure_one()
        return safe_eval(self.domain)

    def get_description(self, record):
        self.ensure_one()

        if not self.description:
            return ""

        if self.description_template_type == "plain":
            return self.description
        elif self.description_template_type == "jinja":
            return self._render_description_by_jinja(record)
        elif self.description_template_type == "variables":
            return self._render_description_by_variables(record)

    def description_needs_rendering(self):
        self.ensure_one()

        return self.description and self.description_template_type != "plain"

    def _render_description_by_jinja(self, record):
        self.ensure_one()

        res = None
        try:
            res = self.env["mail.render.mixin"]._render_template(
                self.description,
                record._name,
                [record.id],
                add_context=self._render_description_context(record),
            )[record.id]

            # Check _render_template_jinja. If the template cannot be loaded,
            # an error is logged an an empty string returned. If self.description
            # is not set, it will not call _render_description_by_jinja
            if not res:
                raise UserError(_("The description contains invalid Jinja syntax"))
        except UserError as e:
            raise UserError(
                _(
                    "Exception rule '%(rule)s' has an invalid Jinja description.\n"
                    "The following error was raised while rendering it:\n\n %(error)s",
                    rule=self.name,
                    error=e,
                )
            )

        return res

    def _render_description_by_variables(self, record):
        code_vars = self._render_description_eval_code(record)
        text = self.description

        try:
            text = text.format(**code_vars)
        except KeyError as e:
            raise UserError(
                _(
                    "Exception rule '%(rule)s' has an invalid description code.\n"
                    "It does not assign a value to the following variable: %(var)s",
                    rule=self.name,
                    var=e.args[0],
                ),
            )

        return text

    def _render_description_context(self, record):
        self.ensure_one()

        return {
            "exception": self,
            "object": record,
        }

    def _render_description_eval_code(self, record):
        space = self._render_description_context(record)
        expr = self.description_variables_code

        try:
            safe_eval(expr, space, mode="exec", nocopy=True)
        except Exception as e:
            raise UserError(
                _(
                    "Couldn't render the description of exception rule '%(rule)s'.\n"
                    "Following error was raised:\n%(error)s",
                    rule=self.name,
                    error=e,
                )
            )

        return space


class BaseExceptionMethod(models.AbstractModel):
    _name = "base.exception.method"
    _description = "Exception Rule Methods"

    def _get_main_records(self):
        """
        Used in case we check exceptions on a record but write these
        exceptions on a parent record. Typical example is with
        sale.order.line. We check exceptions on some sale order lines but
        write these exceptions on the sale order, so they are visible.
        """
        return self

    def _reverse_field(self):
        raise NotImplementedError()

    def _get_sub_exception_field_names(self):
        """
        Used in case exceptions need to be checked on underlying records and the
        detected exceptions need to be added to the parent record.
        """
        return []

    def _rule_domain(self):
        """Filter exception.rules.
        By default, only the rules with the correct model
        will be used.
        """
        return [("model", "=", self._name), ("active", "=", True)]

    def detect_exceptions(self):
        """List all exception_ids applied on self
        Exception ids are also written on records
        """
        rules = self.env["exception.rule"].sudo().search(self._rule_domain())
        all_exception_ids = []
        rules_to_remove = {}
        rules_to_add = {}
        for rule in rules:
            records_with_exception = self._detect_exceptions(rule)
            reverse_field = self._reverse_field()
            main_records = self._get_main_records()
            commons = main_records & rule[reverse_field]
            to_remove = commons - records_with_exception
            to_add = records_with_exception - commons
            # we expect to always work on the same model type
            if rule.id not in rules_to_remove:
                rules_to_remove[rule.id] = main_records.browse()
            rules_to_remove[rule.id] |= to_remove
            if rule.id not in rules_to_add:
                rules_to_add[rule.id] = main_records.browse()
            rules_to_add[rule.id] |= to_add
            if records_with_exception:
                all_exception_ids.append(rule.id)
        # Cumulate all the records to attach to the rule
        # before linking. We don't want to call "rule.write()"
        # which would:
        # * write on write_date so lock the exception.rule
        # * trigger the recomputation of "main_exception_id" on
        #   all the sale orders related to the rule, locking them all
        #   and preventing concurrent writes
        # Reversing the write by writing on SaleOrder instead of
        # ExceptionRule fixes the 2 kinds of unexpected locks.
        # It should not result in more queries than writing on ExceptionRule:
        # the "to remove" part generates one DELETE per rule on the relation
        # table
        # and the "to add" part generates one INSERT (with unnest) per rule.
        for rule_id, records in rules_to_remove.items():
            records.write({"exception_ids": [(3, rule_id)]})
        for rule_id, records in rules_to_add.items():
            records.write({"exception_ids": [(4, rule_id)]})

        # Detect exceptions on underlying sub-records if needed. If the sub-records'
        # model defines the current model in _get_main_records and _reverse_field,
        # the exceptions detected are added to the current record
        for field in self._get_sub_exception_field_names():
            all_exception_ids += self.mapped(field).detect_exceptions()

        return all_exception_ids

    @api.model
    def _exception_rule_eval_context(self, rec):
        return {
            "self": rec,
            "object": rec,
            "obj": rec,
        }

    @api.model
    def _rule_eval(self, rule, rec):
        expr = rule.code
        space = self._exception_rule_eval_context(rec)
        try:
            safe_eval(
                expr, space, mode="exec", nocopy=True
            )  # nocopy allows to return 'result'
        except Exception as e:
            _logger.exception(e)
            raise UserError(
                _(
                    "Error when evaluating the exception.rule rule:\n %s \n(%s)",
                    rule.name,
                    e,
                )
            )
        return space.get("failed", False)

    def _detect_exceptions(self, rule):
        if rule.exception_type == "by_py_code":
            return self._detect_exceptions_by_py_code(rule)
        elif rule.exception_type == "by_domain":
            return self._detect_exceptions_by_domain(rule)
        elif rule.exception_type == "by_method":
            return self._detect_exceptions_by_method(rule)

    def _get_base_domain(self):
        return [("ignore_exception", "=", False), ("id", "in", self.ids)]

    def _detect_exceptions_by_py_code(self, rule):
        """
        Find exceptions found on self.
        """
        domain = self._get_base_domain()
        records = self.search(domain)
        records_with_exception = self.env[self._name]
        for record in records:
            if self._rule_eval(rule, record):
                records_with_exception |= record
        return records_with_exception

    def _detect_exceptions_by_domain(self, rule):
        """
        Find exceptions found on self.
        """
        base_domain = self._get_base_domain()
        rule_domain = rule._get_domain()
        domain = expression.AND([base_domain, rule_domain])
        return self.search(domain)

    def _detect_exceptions_by_method(self, rule):
        """
        Find exceptions found on self.
        """
        base_domain = self._get_base_domain()
        records = self.search(base_domain)
        return getattr(records, rule.method)()


class BaseExceptionModel(models.AbstractModel):
    _inherit = "base.exception.method"
    _name = "base.exception"
    _order = "main_exception_id asc"
    _description = "Exception"

    main_exception_id = fields.Many2one(
        "exception.rule",
        compute="_compute_main_error",
        string="Main Exception",
        store=True,
    )
    exceptions_summary = fields.Html(
        "Exceptions Summary", compute="_compute_exceptions_summary"
    )
    exception_ids = fields.Many2many("exception.rule", string="Exceptions", copy=False)
    ignore_exception = fields.Boolean("Ignore Exceptions", copy=False)

    def action_ignore_exceptions(self):
        if any(self.exception_ids.mapped("is_blocking")):
            raise UserError(
                _(
                    "The exceptions can not be ignored, because "
                    "some of them are blocking."
                )
            )
        self.write({"ignore_exception": True})
        return True

    @api.depends("exception_ids", "ignore_exception")
    def _compute_main_error(self):
        for rec in self:
            if not rec.ignore_exception and rec.exception_ids:
                rec.main_exception_id = rec.exception_ids[0]
            else:
                rec.main_exception_id = False

    @api.depends(
        "exception_ids",
        "exception_ids.description_template_type",
        "exception_ids.description_variables_code",
        "ignore_exception",
    )
    def _compute_exceptions_summary(self):
        for rec in self:
            if rec.exception_ids and not rec.ignore_exception:
                rec.exceptions_summary = rec._get_exception_summary()
            else:
                rec.exceptions_summary = False

    def _get_exception_summary(self):
        self.ensure_one()

        summaries = []
        sub_fields = self._get_sub_exception_field_names()

        for e in self.exception_ids:
            if e.model == self._name:
                summaries.append(self._get_exception_summary_for_exception_rule(e))
                continue

            for field in sub_fields:
                sub_records = self.mapped(field)
                if e.model != sub_records._name:
                    continue

                for sub_record in sub_records:
                    if e in sub_record.exception_ids:
                        sub_summary = (
                            sub_record._get_exception_summary_for_exception_rule(e)
                        )
                        # Duplicates are possible if an exception of a sub-record
                        # has a plain text description. Do not use a set as a set
                        # will not preserve the order of exceptions
                        if sub_summary not in summaries:
                            summaries.append(sub_summary)

        return "<ul>%s</ul>" % "".join(summaries)

    def _get_exception_summary_for_exception_rule(self, rule):
        self.ensure_one()

        return "<li>%s: <i>%s</i> <b>%s</b></li>" % tuple(
            map(
                html.escape,
                (
                    rule.name,
                    rule.get_description(self) or "",
                    _("(Blocking exception)") if rule.is_blocking else "",
                ),
            )
        )

    def _popup_exceptions(self):
        action = self._get_popup_action().sudo().read()[0]
        action.update(
            {
                "context": {
                    "active_id": self.ids[0],
                    "active_ids": self.ids,
                    "active_model": self._name,
                }
            }
        )
        return action

    @api.model
    def _get_popup_action(self):
        return self.env.ref("base_exception.action_exception_rule_confirm")

    def _check_exception(self):
        """Check exceptions

        This method must be used in a constraint that must be created in the
        object that inherits for base.exception.

        .. code-block:: python

            @api.constrains("ignore_exception")
            def sale_check_exception(self):
                # ...
                self._check_exception()

        For convenience, this check can be skipped by setting check_exception=False
        in context.

        Exceptions will be raised as ValidationError, but this can be disabled
        by setting raise_exception=False in context. They will still be detected
        and updated on the related record, though.
        """
        if not self.env.context.get("check_exception", True):  # pragma: no cover
            return True
        exception_ids = self.detect_exceptions()
        if exception_ids and self.env.context.get("raise_exception", True):
            exceptions = self.env["exception.rule"].browse(exception_ids)
            raise ValidationError("\n".join(exceptions.mapped("name")))
