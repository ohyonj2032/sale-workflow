import os

base_dir = '/app/sale-workflow/sale_workflow'
dirs = [
    '',
    'models',
    'controllers',
    'views',
    'i18n',
    'tests',
]

for d in dirs:
    os.makedirs(os.path.join(base_dir, d), exist_ok=True)

print("Directories created.")
