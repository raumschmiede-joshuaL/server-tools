# Copyright 2016 Akretion Mourad EL HADJ MIMOUNE
# Copyright 2020 Hibou Corp.
# Copyright 2025 Raumschmiede GmbH
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).


from odoo.exceptions import UserError, ValidationError

from .common import TestBaseExceptionCommon


class TestBaseException(TestBaseExceptionCommon):
    def test_01_valid(self):
        self.exception_rule.active = False
        self.po.button_confirm()
        self.assertFalse(self.po.exception_ids)

    def test_02_fail_by_py(self):
        with self.assertRaises(ValidationError):
            self.po.button_confirm()
        self.assertEqual(self.po.exception_ids, self.exception_rule)

    def test_03_fail_by_domain(self):
        self.exception_rule.write(
            {
                "domain": "[('partner_id.zip', '=', False)]",
                "exception_type": "by_domain",
            }
        )
        with self.assertRaises(ValidationError):
            self.po.button_confirm()
        self.assertEqual(self.po.exception_ids, self.exception_rule)
        self.assertIn(self.exception_rule.description, self.po.exceptions_summary)

    def test_04_fail_by_method(self):
        self.exception_rule.write(
            {
                "method": "exception_method_no_zip",
                "exception_type": "by_method",
            }
        )
        with self.assertRaises(ValidationError):
            self.po.button_confirm()
        self.assertEqual(self.po.exception_ids, self.exception_rule)

    def test_05_ignorable_exception(self):
        # Block because of exception during validation
        with self.assertRaises(ValidationError):
            self.po.button_confirm()
        # Test that we have linked exceptions
        self.assertEqual(self.po.exception_ids, self.exception_rule)
        # Test ignore exeception make possible for the po to validate
        self.po.action_ignore_exceptions()
        self.assertTrue(self.po.ignore_exception)
        self.assertFalse(self.po.exceptions_summary)
        self.po.button_confirm()
        self.assertEqual(self.po.state, "purchase")

    def test_06_blocking_exception(self):
        self.exception_rule.is_blocking = True
        # Block because of exception during validation
        with self.assertRaises(ValidationError):
            self.po.button_confirm()
        # Test that we have linked exceptions
        self.assertEqual(self.po.exception_ids, self.exception_rule)
        self.assertTrue(self.po.exceptions_summary)
        # Test cannot ignore blocked exception
        with self.assertRaises(UserError):
            self.po.action_ignore_exceptions()
        self.assertFalse(self.po.ignore_exception)
        with self.assertRaises(ValidationError):
            self.po.button_confirm()
        self.assertEqual(self.po.exception_ids, self.exception_rule)
        self.assertTrue(self.po.exceptions_summary)

    def test_07_exception_in_sub_record(self):
        self.exception_rule.active = False
        self.po.line_ids[0].amount = 90

        # Now only sub_exception_rule_parent must raise the error
        with self.assertRaises(ValidationError):
            self.po.button_confirm()

        self.assertEqual(self.po.exception_ids, self.sub_exception_rule_parent)
        # Even if the exception was not raised by self.po, its description must still
        # be in the summary of it
        self.assertIn(
            self.sub_exception_rule_parent.description, self.po.exceptions_summary
        )

        self.assertEqual(
            self.po.line_ids[0].exception_ids, self.sub_exception_rule_parent
        )
        self.assertIn(
            self.sub_exception_rule_parent.description,
            self.po.line_ids[0].exceptions_summary,
        )
        # self.po has 2 lines, the exception is detected only on the 1st line.
        # The 2nd must not have any exception assigned or summary
        self.assertFalse(self.po.line_ids[1].exception_ids)
        self.assertFalse(self.po.line_ids[1].exceptions_summary)

        self.exception_rule.active = True

        self.po.detect_exceptions()

        # Now both exceptions must be assigned to the record, in the right order
        self.assertEqual(self.po.exception_ids[0], self.sub_exception_rule_parent)
        self.assertEqual(self.po.exception_ids[1], self.exception_rule)

        self.po.line_ids[1].amount = 80
        self.po.detect_exceptions()

        self.assertEqual(
            self.po.line_ids[0].exception_ids, self.sub_exception_rule_parent
        )
        self.assertEqual(
            self.po.line_ids[1].exception_ids, self.sub_exception_rule_parent
        )
        self.assertIn(
            self.sub_exception_rule_parent.description,
            self.po.line_ids[1].exceptions_summary,
        )

        # As both lines have the same exception but the description is not unique per
        # line, the description must only be once in the summary of self.po
        self.assertEqual(self.po.exceptions_summary.count("price"), 1)

        line = self.po.line_ids[0]
        line.amount = 200
        line.detect_exceptions()

        # Updating exceptions on a sub-record updates exceptions on the parent because
        # _get_main_records returns the parent
        self.assertFalse(line.exception_ids)
        self.assertEqual(self.po.exception_ids, self.exception_rule)

        self.sub_exception_rule_self.active = True
        line = self.po.line_reverse_self_ids[0]
        line.amount = 75
        line.detect_exceptions()

        self.assertEqual(line.exception_ids, self.sub_exception_rule_self)
        # The sub-exception is detected but it is not assigned to self.po. The model
        # test.purchase.line.reverse.self does not return its parent record in
        # _reverse_field and _get_main_records
        self.assertIn(self.sub_exception_rule_self.id, self.po.detect_exceptions())
        self.assertNotIn(self.sub_exception_rule_self, self.po.exception_ids)

    def test_08_description_jinja_success(self):
        desc = "${object.partner_id.name} has no ZIP. Model: ${exception.model}"
        self.exception_rule.description = desc

        self.po.detect_exceptions()

        # description_template_type was not changed. description must be handled
        # as plain text
        self.assertIn("object.partner_id.name", self.po.exceptions_summary)

        self.exception_rule.description_template_type = "jinja"
        self.po.detect_exceptions()

        self.assertIn(self.po.partner_id.name, self.po.exceptions_summary)
        self.assertIn(self.po._name, self.po.exceptions_summary)

        self.sub_exception_rule_parent.description = (
            "Line's price ${object.amount} is lower than 100"
        )
        self.sub_exception_rule_parent.description_template_type = "jinja"
        line = self.po.line_ids[0]
        line.amount = 90
        self.po.detect_exceptions()

        self.assertIn(str(line.amount), self.po.exceptions_summary)
        self.assertIn(str(line.amount), line.exceptions_summary)

        line2 = self.po.line_ids[1]
        line2.amount = 80
        self.po.detect_exceptions()
        self.po.invalidate_cache()

        # Both lines have the same exception but each line has a unique description.
        # Summary of parent must have both descriptions
        self.assertIn(str(line.amount), self.po.exceptions_summary)
        self.assertIn(str(line2.amount), self.po.exceptions_summary)
        self.assertIn(str(line2.amount), line2.exceptions_summary)
        self.assertNotIn(str(line.amount), line2.exceptions_summary)

    def test_09_description_variables_sucess(self):
        self.exception_rule.description = "{partner} has no ZIP"
        code = "partner = object.partner_id.name + str(exception.id)"
        self.exception_rule.description_variables_code = code

        self.po.detect_exceptions()

        # description_template_type was not changed. description must be handled
        # as plain text
        self.assertIn("{partner}", self.po.exceptions_summary)

        self.exception_rule.description_template_type = "variables"
        self.po.detect_exceptions()

        self.assertIn(self.po.partner_id.name, self.po.exceptions_summary)
        self.assertIn(str(self.exception_rule.id), self.po.exceptions_summary)

        self.sub_exception_rule_parent.description = (
            "Line's price {price} is lower than 100"
        )
        self.sub_exception_rule_parent.description_template_type = "variables"
        self.sub_exception_rule_parent.description_variables_code = (
            "price = object.amount"
        )
        line = self.po.line_ids[0]
        line.amount = 90
        self.po.detect_exceptions()

        self.assertIn(str(line.amount), self.po.exceptions_summary)
        self.assertIn(str(line.amount), line.exceptions_summary)

        line2 = self.po.line_ids[1]
        line2.amount = 80
        self.po.detect_exceptions()
        self.po.invalidate_cache()

        # Both lines have the same exception but each line has a unique description.
        # Summary of parent must have both descriptions
        self.assertIn(str(line.amount), self.po.exceptions_summary)
        self.assertIn(str(line2.amount), self.po.exceptions_summary)
        self.assertIn(str(line2.amount), line2.exceptions_summary)
        self.assertNotIn(str(line.amount), line2.exceptions_summary)

    def test_10_description_jinja_error(self):
        self.exception_rule.description = "Partner ${name.field} has no ZIP"
        self.exception_rule.description_template_type = "jinja"

        self.po.detect_exceptions()
        # Computation of exceptions_summary raises an error.
        # Here because "name" is not available in the Jinja context
        with self.assertRaises(UserError) as e:
            self.po._compute_exceptions_summary()
        self.assertIn("is undefined", str(e.exception))

        desc = "Partner ${object.filtered(lambda o: o.name)} has no ZIP"
        self.exception_rule.description = desc

        self.po.detect_exceptions()
        # Jinja doesn't like lambda
        with self.assertRaises(UserError) as e:
            self.po._compute_exceptions_summary()
        self.assertIn("invalid Jinja syntax", str(e.exception))

        desc = "Partner ${object.unexisting_field} has no ZIP"
        self.exception_rule.description = desc

        # Using an non-existing field works but nothing is rendered
        self.po.detect_exceptions()
        self.assertIn("Partner  has no ZIP", self.po.exceptions_summary)

        desc = "Partner ${object.fi.fu} has no ZIP"
        self.exception_rule.description = desc

        self.po.detect_exceptions()
        # But Jinja raises an error when a sub-field is used of a non-existing field
        with self.assertRaises(UserError) as e:
            self.po._compute_exceptions_summary()
        self.assertIn("has no attribute 'fi'", str(e.exception))

    def test_11_description_variables_error(self):
        self.exception_rule.description = "{partner} has no ZIP"
        code = "import re\npartner = object.name"
        self.exception_rule.description_variables_code = code
        self.exception_rule.description_template_type = "variables"

        self.po.detect_exceptions()
        with self.assertRaises(UserError) as e:
            self.po._compute_exceptions_summary()

        self.assertIn("forbidden opcode", str(e.exception))

        self.exception_rule.description_variables_code = "partner = 1 / 0"

        self.po.detect_exceptions()
        with self.assertRaises(UserError) as e:
            self.po._compute_exceptions_summary()
        self.assertIn("division by zero", str(e.exception))

        self.exception_rule.description_variables_code = "partner = a"

        self.po.detect_exceptions()
        with self.assertRaises(UserError) as e:
            self.po._compute_exceptions_summary()
        self.assertIn("NameError", str(e.exception))

        self.exception_rule.description_variables_code = "a = 1"

        self.po.detect_exceptions()
        with self.assertRaises(UserError) as e:
            self.po._compute_exceptions_summary()
        self.assertIn("following variable: partner", str(e.exception))
