{
    "name": "Sale Advanced Workflow",
    "summary": "Add pending review state to sale orders with invoice generation",
    "version": "16.0.1.0.0",
    "category": "Sale",
    "website": "https://github.com/OCA/sale-workflow",
    "author": "Odoo Community Association (OCA)",
    "license": "AGPL-3",
    "application": False,
    "installable": True,
    "depends": [
        "sale",
        "account",
    ],
    "data": [
        "views/sale_order_views.xml",
    ],
}
