import os
import difflib

patch_file = '/app/sale-workflow/5.3.3.patch'
target_dir = '/app/sale-workflow/sale_workflow'

with open(patch_file, 'w', encoding='utf-8') as pf:
    for root, dirs, files in os.walk(target_dir):
        for f in sorted(files):
            filepath = os.path.join(root, f)
            rel_path = os.path.relpath(filepath, '/app/sale-workflow')
            
            with open(filepath, 'r', encoding='utf-8') as infile:
                lines = infile.readlines()
            
            # Ensure lines end with newline
            lines = [line if line.endswith('\n') else line + '\n' for line in lines]
            
            a_name = 'a/' + rel_path
            b_name = 'b/' + rel_path
            
            diff = list(difflib.unified_diff(
                [],
                lines,
                fromfile=a_name,
                tofile=b_name,
            ))
            
            pf.writelines(diff)

print("Patch generated successfully.")
