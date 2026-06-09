# Copyright 2018 Akretion (http://www.akretion.com).
# @author Pierrick BRUN <pierrick.brun@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
# Copyright 2026 Credit Hold Enhancement

{
    "name": "Sale delivery State",
    "summary": "Show the delivery state on the sale order, with credit hold mechanism",
    "version": "18.0.1.3.0",
    "category": "Product",
    "website": "https://github.com/OCA/sale-workflow",
    "author": "Akretion, Odoo Community Association (OCA)",
    "license": "AGPL-3",
    "installable": True,
    "depends": ["sale", "sale_stock"],
    "data": [
        "security/sale_delivery_state_security.xml",
        "security/ir.model.access.csv",
        "views/sale_order_views.xml",
        "views/res_config_settings_views.xml",
    ],
    "demo": [
        "demo/sale_demo.xml",
    ],
    "pre_init_hook": "pre_init_hook",
    "post_init_hook": "post_init_hook",
}
