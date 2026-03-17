pip install build twine

cd C:\Users\richi\TI_richiebao\YINGZAOLAB\YingZao_PyPI
python -m build

python -m twine upload dist/yingzao-1.0.0.tar.gz dist/yingzao-1.0.0-py3-none-any.whl
python -m twine check dist/*
python -m twine upload dist/*
python -m twine upload dist/yingzao-1.0.0*

pip install C:\Users\richi\TI_richiebao\YINGZAOLAB\YingZao_PyPI\dist\yingzao-1.0.0.tar.gz



