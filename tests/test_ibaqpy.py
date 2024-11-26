from unittest import TestCase
from ibaqpy.bin.compute_ibaq import ibaq_compute
from .common import datafile

class TestIbaqpy(TestCase):

    def test_ibaq_compute(self):
        args = {
            "fasta": datafile("Homo-sapiens-uniprot-reviewed-contaminants-decoy-202210.fasta"),
            "peptides": datafile("PXD017834-peptides.csv"),
            "enzyme": "Trypsin",
            "normalize": True,
            "min_aa": 7,
            "max_aa": 30,
            "output": datafile("PXD017834-ibaq-norm.csv"),
            "verbose": True,
            "qc_report": datafile("IBAQ-QCprofile.pdf"),
        }
        print(args)
        ibaq_compute(**args)
