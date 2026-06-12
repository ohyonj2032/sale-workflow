# Copyright 2025 Odoo Community Association (OCA)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
{
    "name": "Sale Advanced Workflow",
    "summary": "Add pending review state to sale orders with amount threshold validation",
    "version": "16.0.1.0.0",
    "category": "Sales/Sales",
    "author": "Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/sale-workflow",
    "depends": ["sale", "account"],
    "license": "AGPL-3",
    "data": [
        "views/sale_order_views.xml",
    ],
    "installable": True,
}
