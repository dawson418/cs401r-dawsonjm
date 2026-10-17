import nbformat as nbf
nb = nbf.v4.new_notebook()
c = [
 nbf.v4.new_markdown_cell("# NorthStar Lab 3 demo: churn model (Track A) and RAG offers (Track B)"),
 nbf.v4.new_code_cell("import json, sys, pathlib\nimport pandas as pd\nfrom IPython.display import Image, display\nROOT = pathlib.Path.cwd().parent if pathlib.Path.cwd().name == 'notebooks' else pathlib.Path.cwd()\nsys.path.insert(0, str(ROOT))\nimport os; os.chdir(ROOT)\nEV = 'docs/lab3-evidence'"),
 nbf.v4.new_markdown_cell("## Track A: graded run metrics"),
 nbf.v4.new_code_cell("print(json.dumps(json.load(open(f'{EV}/evaluation_metrics.json')), indent=2))"),
 nbf.v4.new_code_cell("pd.read_csv(f'{EV}/slice-evaluation.csv')"),
 nbf.v4.new_code_cell("display(Image(f'{EV}/confusion-matrix.png')); display(Image(f'{EV}/feature-importance.png'))"),
 nbf.v4.new_markdown_cell("## Track B: retention offers from the RAG pipeline"),
 nbf.v4.new_code_cell("from rag.pipeline import generate_offer, SAMPLE_PROFILES"),
 nbf.v4.new_code_cell("for p in SAMPLE_PROFILES:\n    o = generate_offer(p)\n    print(p['loyalty_tier'], p['top_categories'])\n    print(' ', o['offer'])\n    print('  chunks:', o['chunk_ids'], '\\n')"),
]
nb["cells"] = c
nbf.write(nb, "notebooks/lab3-demo.ipynb")
