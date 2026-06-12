# -*- coding: utf-8 -*-
{
    'name': "Sale Advanced Workflow",
    'summary': """
        Extends the sale order workflow with a Pending Review state.
    """,
    'description': """
        This module adds a 'Pending Review' state to Sale Orders.
        Orders that are confirmed and have an amount greater than a specific threshold
        require a review and trigger invoice generation.
    """,
    'author': "Your Company",
    'website': "https://www.yourcompany.com",
    'category': 'Sales',
    'version': '16.0.1.0.0',
    'depends': ['sale', 'account'],
    'data': [
        'views/sale_order_views.xml',
    ],
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
}
