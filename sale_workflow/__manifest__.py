{
    'name': 'Sale Workflow',
    'version': '16.0.1.0.0',
    'category': 'Sales',
    'summary': 'Refactored sale workflow module',
    'depends': [
        'sale_management',
        'stock',
    ],
    'data': [
        'views/sale_order_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
