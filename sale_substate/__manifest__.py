# Copyright 2019 Akretion (<http://www.akretion.com>)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

{
    "name": "Sale Workflow",
    "summary": "Centralized sale order state machine with partial delivery support",
    "version": "16.0.1.0.0",
    "category": "Sales/Sales",
    "author": "Akretion, Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/sale-workflow",
    "license": "AGPL-3",
    "depends": ["sale_management"],
    "data": [
        "data/sale_substate_data.xml",
        "data/sale_substate_mail_template_data.xml",
        "views/sale_order_views.xml",
    ],
    "demo": [
        "data/sale_substate_demo.xml",
    ],
    "installable": True,
    "application": False,
}
