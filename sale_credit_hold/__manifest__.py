{
    "name": "Sale Credit Hold",
    "summary": "Add credit hold functionality to sale orders to block deliveries when credit limit is exceeded",
    "version": "16.0.1.0.0",
    "category": "Sales",
    "website": "https://github.com/OCA/sale-workflow",
    "author": "Odoo Community Association (OCA)",
    "license": "AGPL-3",
    "installable": True,
    "depends": ["sale_stock"],
    "data": [
        "security/ir.model.access.csv",
        "security/sale_credit_hold_security.xml",
        "views/sale_order_views.xml",
        "views/res_partner_views.xml",
    ],
    "pre_init_hook": "pre_init_hook",
}