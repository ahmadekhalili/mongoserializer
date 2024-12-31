from setuptools import setup, find_packages

setup(
    name='mongoserializer',
    version='1.0.1',
    packages=['mongoserializer'],
    install_requires=["django", "djangorestframework", "pymongo"],
    extras_require={
        'jalali': ['jdatetime']
    },
    author='Ahmad Khalili',
    author_email='ahmadkhalili2020@gmail.com',
    description='One of the best practices for interacting with MongoDB in a Django REST environment',
    license='MIT',
    long_description=open('README.md', encoding='utf-8').read(),
    long_description_content_type='text/markdown',
    url='https://github.com/ahmadekhalili/onetomultipleimage',
    include_package_data=True,
    classifiers=[
        'Framework :: Django',
        'Framework :: Django :: 3',
        'Framework :: Django :: 4',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'License :: OSI Approved :: MIT License',
    ],
)
