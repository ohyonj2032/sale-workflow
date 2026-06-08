{
    'name': 'Sale Advanced Workflow',
    'version': '16.0.1.0.0',
    'category': 'Sales',
    'summary': 'Adds pending review state to sale orders with amount threshold check',
    'author': 'Your Company',
    'website': 'https://www.odoo.com',
    'depends': ['sale', 'account'],
    'data': [
        'views/sale_order_views.xml',
    ],
    'demo': [],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
