import re
from typing import OrderedDict

import click
import matplotlib
import numpy as np
import pandas as pd
import seaborn as sns

from matplotlib import pyplot as plt
from pandas import DataFrame

PROTEIN_NAME = 'ProteinName'
PEPTIDE_SEQUENCE = 'PeptideSequence'
PEPTIDE_CANONICAL = "PeptideCanonical"
PEPTIDE_CHARGE = 'PrecursorCharge'
FRAGMENT_ION = 'FragmentIon'
PRODUCT_CHARGE = 'ProductCharge'
ISOTOPE_LABEL_TYPE = 'IsotopeLabelType'
CHANNEL = 'Channel'
MIXTRUE = 'Mixture'
TECHREPMIXTURE = 'TechRepMixture'
CONDITION = 'Condition'
BIOREPLICATE = 'BioReplicate'
RUN = 'Run'
FRACTION = 'Fraction'
INTENSITY = 'Intensity'
NORM_INTENSITY = 'NormIntensity'
RT = 'Rt'
REFERENCE = 'Reference'
SAMPLE_ID = 'SampleID'
STUDY_ID = 'StudyID'
SEARCH_ENGINE = 'searchScore'
SCAN = 'Scan'
MBR = 'MatchBetweenRuns'
IBAQ = 'Ibaq'
IBAQ_NORMALIZED = 'IbaqNorm'
IBAQ_LOG = 'IbaqLog'
IBAQ_PPB = 'IbaqPpb'

TMT16plex = {
    "TMT126": 1,
    "TMT127N": 2,
    "TMT127C": 3,
    "TMT128N": 4,
    "TMT128C": 5,
    "TMT129N": 6,
    "TMT129C": 7,
    "TMT130N": 8,
    "TMT130C": 9,
    "TMT131N": 10,
    "TMT131C": 11,
    "TMT132N": 12,
    "TMT132C": 13,
    "TMT133N": 14,
    "TMT133C": 15,
    "TMT134N": 16,
}

TMT11plex = {
    "TMT126": 1,
    "TMT127N": 2,
    "TMT127C": 3,
    "TMT128N": 4,
    "TMT128C": 5,
    "TMT129N": 6,
    "TMT129C": 7,
    "TMT130N": 8,
    "TMT130C": 9,
    "TMT131N": 10,
    "TMT131C": 11,
}

TMT10plex = {
    "TMT126": 1,
    "TMT127N": 2,
    "TMT127C": 3,
    "TMT128N": 4,
    "TMT128C": 5,
    "TMT129N": 6,
    "TMT129C": 7,
    "TMT130N": 8,
    "TMT130C": 9,
    "TMT131": 10,
}

TMT6plex = {"TMT126": 1, "TMT127": 2, "TMT128": 3, "TMT129": 4, "TMT130": 5, "TMT131": 6}

ITRAQ4plex = {"ITRAQ114": 1, "ITRAQ115": 2, "ITRAQ116": 3, "ITRAQ117": 4}

ITRAQ8plex = {
    "ITRAQ113": 1,
    "ITRAQ114": 2,
    "ITRAQ115": 3,
    "ITRAQ116": 4,
    "ITRAQ117": 5,
    "ITRAQ118": 6,
    "ITRAQ119": 7,
    "ITRAQ121": 8,
}


def print_help_msg(command: click.Command):
    """
    Print the help of the command
    :param command: click command object
    :return: None
    """
    with click.Context(command) as ctx:
        click.echo(command.get_help(ctx))


def remove_contaminants_decoys(dataset: DataFrame, contaminants_file: str, protein_field=PROTEIN_NAME) -> DataFrame:
    """
    This method reads a file with a list of contaminants and high abudant proteins and
    remove them from the dataset.
    :param dataset: Peptide intensity DataFrame
    :param contaminants_file: contaminants file
    :param protein_field: protein field
    :return: dataset with the filtered proteins
    """
    contaminants_reader = open(contaminants_file, 'r')
    contaminants = contaminants_reader.read().split("\n")
    contaminants = [cont for cont in contaminants if cont.strip()]

    contaminants.append('CONTAMINANT')
    contaminants.append('DECOY')
    # cregex = ".*(" + '|'.join(contaminants) + ").*"
    cregex = '|'.join(contaminants)
    # for contaminant in contaminants:
    # dataset.drop(index=dataset[dataset[protein_field].str.contains(contaminant)].index, inplace=True)

    return dataset[~dataset[protein_field].str.contains(cregex)]


def get_canonical_peptide(peptide_sequence: str) -> str:
    """
    This function returns a peptide sequence without the modification information
    :param peptide_sequence: peptide sequence with mods
    :return: peptide sequence
    """
    clean_peptide = re.sub("[\(\[].*?[\)\]]", "", peptide_sequence)
    clean_peptide = clean_peptide.replace(".", "")
    return clean_peptide


def plot_distributions(dataset: DataFrame, field: str, class_field: str, title: str = "", log2: bool = True,
                       weight: float = 10) -> matplotlib.pyplot:
    """
    Print the quantile plot for the dataset
    :param dataset: DataFrame
    :param field: Field that would be use in the dataframe to plot the quantile
    :param class_field: Field to group the quantile into classes
    :param title: Title of the box plot
    :param log2: Log the intensity values
    :param weight: size of the plot
    :return:
    """
    pd.set_option('mode.chained_assignment', None)
    normalize = dataset[[field, class_field]]
    if log2:
        normalize[field] = np.log2(normalize[field])
    normalize.dropna(subset=[field], inplace=True)
    data_wide = normalize.pivot(columns=class_field,
                                values=field)
    # plotting multiple density plot
    data_wide.plot.kde(figsize=(weight, 8), linewidth=2, legend=False)
    plt.title(title)
    pd.set_option('mode.chained_assignment', 'warn')

    return plt.gcf()


def plot_box_plot(dataset: DataFrame, field: str, class_field: str, log2: bool = False, weigth: int = 10,
                  rotation: int = 30, title: str = "", violin: bool = False) -> matplotlib.pyplot:
    """
    Plot a box plot of two values field and classes field
    :param violin: Also add violin on top of box plot
    :param dataset: Dataframe with peptide intensities
    :param field: Intensity field
    :param class_field: class to group the peptides
    :param log2: transform peptide intensities to log scale
    :param weigth: size of the plot
    :param rotation: rotation of the x-axis
    :param title: Title of the box plot
    :return:
    """
    pd.set_option('mode.chained_assignment', None)
    normalized = dataset[[field, class_field]]
    np.seterr(divide='ignore')
    plt.figure(figsize=(weigth, 14))
    if log2:
        normalized[field] = np.log2(normalized[field])

    if violin:
        chart = sns.violinplot(x=class_field, y=field, data=normalized, boxprops=dict(alpha=.3), palette="muted")
    else:
        chart = sns.boxplot(x=class_field, y=field, data=normalized, boxprops=dict(alpha=.3), palette="muted")

    chart.set(title=title)
    chart.set_xticklabels(chart.get_xticklabels(), rotation=rotation, ha='right')
    pd.set_option('mode.chained_assignment', 'warn')

    return plt.gcf()


def remove_extension_file(filename: str) -> str:
    """
  The filename can have
  :param filename:
  :return:
  """
    return filename.replace('.raw', '').replace('.RAW', '').replace('.mzML', '').replace('.wiff', '')


def sum_peptidoform_intensities(dataset: DataFrame) -> DataFrame:
    """
    Sum the peptidoform intensities for all peptidofrom across replicates of the same sample.
    :param dataset: Dataframe to be analyzed
    :return: dataframe with the intensities
    """
    dataset = dataset[dataset[NORM_INTENSITY].notna()]
    normalize_df = dataset.groupby([PEPTIDE_CANONICAL, SAMPLE_ID, BIOREPLICATE, CONDITION])[NORM_INTENSITY].sum()
    normalize_df = normalize_df.reset_index()
    normalize_df = pd.merge(normalize_df,
                            dataset[[PROTEIN_NAME, PEPTIDE_CANONICAL, SAMPLE_ID, BIOREPLICATE, CONDITION]], how='left',
                            on=[PEPTIDE_CANONICAL, SAMPLE_ID, BIOREPLICATE, CONDITION])

    return normalize_df


def get_mbr_hit(scan: str):
    """
  This function annotates if the peptide is inferred or not by Match between Runs algorithm (1), 0 if the peptide is
  identified in the corresponding file.
  :param scan: scan value
  :return:
  """
    return 1 if pd.isna(scan) else 0


def parse_uniprot_accession(uniprot_id: str) -> str:
    """
    Parse the uniprot accession from the uniprot id in the form of
    tr|CONTAMINANT_Q3SX28|CONTAMINANT_TPM2_BOVIN and convert to CONTAMINANT_TPM2_BOVIN
    :param uniprot_id: uniprot id
    :return: uniprot accession
    """
    uniprot_list = uniprot_id.split(";")
    result_uniprot_list = []
    for accession in uniprot_list:
        if accession.count("|") == 2:
            accession = accession.split("|")[2]
        result_uniprot_list.append(accession)
    return ";".join(result_uniprot_list)


def get_study_accession(sample_id: str) -> str:
    """
  Get the project accession from the Sample accession. The function expected a sample accession in the following
  format PROJECT-SAMPLEID
  :param sample_id: Sample Accession
  :return: study accession
  """
    return sample_id.split('-')[0]


def get_reference_name(reference_spectrum: str) -> str:
    """
    Get the reference name from Reference column. The function expected a reference name in the following format eg.
    20150820_Haura-Pilot-TMT1-bRPLC03-2.mzML_controllerType=0 controllerNumber=1 scan=16340
    :param reference_spectrum:
    :return: reference name
    """
    return re.split(r'\.mzML|\.MZML|\.raw|\.RAW', reference_spectrum)[0]


def get_run_mztab(ms_run: str, metadata: OrderedDict) -> str:
    """
  Convert the ms_run into a reference file for merging with msstats output
  :param ms_run: ms_run index in mztab
  :param metadata:  metadata information in mztab
  :return: file name
  """
    m = re.search(r"\[([A-Za-z0-9_]+)\]", ms_run)
    file_location = metadata['ms_run[' + str(m.group(1)) + "]-location"]
    file_location = remove_extension_file(file_location)
    return os.path.basename(file_location)


def get_scan_mztab(ms_run: str) -> str:
    """
  Get the scan number for an mzML spectrum in mzTab. The format of the reference
  must be controllerType=0 controllerNumber=1 scan=30121
  :param ms_run: the original ms_run reference in mzTab
  :return: the scan index
  """
    reference_parts = ms_run.split()
    return reference_parts[-1]


def best_probability_error_bestsearch_engine(probability: float) -> float:
    """
  Convert probability to a Best search engine score
  :param probability: probability
  :return:
  """
    return 1 - probability