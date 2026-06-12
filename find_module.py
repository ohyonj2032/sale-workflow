import os

for root, dirs, files in os.walk('/app/sale-workflow'):
    for d in dirs:
        if 'sale' in d and 'workflow' in d:
            print(os.path.join(root, d))
