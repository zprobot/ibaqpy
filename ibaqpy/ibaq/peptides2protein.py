import math
import pandas as pd
import numpy as np
from ibaqpy.data.data import histones
from matplotlib.backends.backend_pdf import PdfPages
from pandas import DataFrame, Series
from pyopenms import AASequence, ProteaseDigestion, FASTAFile
from typing import List

from ibaqpy.ibaq.ibaqpy_commons import (
    CONDITION,
    IBAQ,
    IBAQ_LOG,
    IBAQ_NORMALIZED,
    IBAQ_PPB,
    NORM_INTENSITY,
    PROTEIN_NAME,
    SAMPLE_ID,
    TPA,
    MOLECULARWEIGHT,
    COPYNUMBER,
    CONCENTRATION_NM,
    MOLES_NMOL,
    WEIGHT_NG,
    plot_box_plot,
    plot_distributions,
    get_accession,
)


def normalize(group):
    """
    Normalize the ibaq values using the total ibaq of the sample.
    This method is called rIBAQ, originally published in https://pubs.acs.org/doi/10.1021/pr401017h
    :param group: Dataframe with all the ibaq values
    :return: Dataframe with the normalized ibaq values
    """
    group[IBAQ_NORMALIZED] = group[IBAQ] / group[IBAQ].sum()
    return group


def normalize_ibaq(res: DataFrame) -> DataFrame:
    """
    Normalize the ibaq values using the total ibaq of the sample. The resulted
    ibaq values are then multiplied by 100'000'000 (PRIDE database noramalization)
    for the ibaq ppb and log10 shifted by 10 (ProteomicsDB)
    :param res: Dataframe
    :return:
    """
    res = res.groupby([SAMPLE_ID, CONDITION]).apply(normalize)
    # Normalization method used by Proteomics DB 10 + log10(ibaq/sum(ibaq))
    res[IBAQ_LOG] = res[IBAQ_NORMALIZED].apply(lambda x: (math.log10(x) + 10) if x > 0 else 0)
    # Normalization used by PRIDE Team (no log transformation) (ibaq/total_ibaq) * 100'000'000
    res[IBAQ_PPB] = res[IBAQ_NORMALIZED].apply(lambda x: x * 100000000)
    return res


def handle_nonstandard_aa(aa_seq: str):
    """
    Any nonstandard amino acid will be removed.
    :param aa_seq: Protein sequences from multiple database.
    :return: One list contains nonstandard amoni acids and one remain sequence.
    """
    standard_aa = "ARNDBCEQZGHILKMFPSTWYV"
    nonstandard_aa_lst = [aa for aa in aa_seq if aa not in standard_aa]
    considered_seq = "".join([aa for aa in aa_seq if aa in standard_aa])
    return nonstandard_aa_lst, considered_seq


def extract_fasta(fasta: str, enzyme: str, proteins: List, min_aa: int, max_aa: int, tpa: bool):
    mw_dict = dict()
    fasta_proteins = list()
    FASTAFile().load(fasta, fasta_proteins)
    found_proteins = set()
    uniquepepcounts = dict()
    digestor = ProteaseDigestion()
    digestor.setEnzyme(enzyme)
    mw_dict = dict()
    for entry in fasta_proteins:
        accession = get_accession(entry.identifier)
        if accession in proteins:
            found_proteins.add(accession)
            digest = list()
            digestor.digest(AASequence().fromString(entry.sequence), digest, min_aa, max_aa)
            digestuniq = set(digest)
            uniquepepcounts[accession] = len(digestuniq)
            if tpa:
                try:
                    mw = AASequence().fromString(entry.sequence).getMonoWeight()
                    mw_dict[accession] = mw
                except ValueError:
                    error_aa, seq = handle_nonstandard_aa(entry.sequence)
                    mw = AASequence().fromString(seq).getMonoWeight()
                    mw_dict[accession] = mw
                    print(f"Nonstandard amino acids found in {accession}: {error_aa}, ignored!")
    if not found_proteins:
        raise ValueError(f"None of the {len(proteins)} proteins were found in the FASTA file")
    return uniquepepcounts, mw_dict, found_proteins


# calculate protein weight(ng) and concentration(nM)
def calculate_weight_and_concentration(
    res: pd.DataFrame, ploidy: int, cpc: float, organism: str, histones: dict
):
    """
    Calculate protein copy number, moles, weight, and concentration for a given dataset.

    This function uses a proteomic ruler approach to estimate the copy number, moles,
    and weight of proteins in a dataset based on their normalized intensity and molecular
    weight. It also calculates the concentration in nM using the total weight and a
    provided concentration per cell (cpc).

    @param res: DataFrame containing protein data with normalized intensity and molecular weight.
    @:param ploidy (int): Ploidy level of the organism.
    @:param cpc (float): Concentration per cell.
    @:param organism (str): Name of the organism.
    @:param histones (dict): Dictionary containing histone information for different organisms.
    @:return pd.DataFrame: Updated DataFrame with calculated copy number, moles, weight,
             and concentration for each protein.
    """
    avogadro = 6.02214129e23
    average_base_pair_mass = 617.96  # 615.8771
    organism = organism.lower()
    histone_df = pd.DataFrame(histones).T
    target_histones = histone_df[histone_df["name"] == organism.lower()]
    genome_size = target_histones["genome_size"].values[0]
    histones_list = target_histones["histone_entries"].values[0]
    dna_mass = ploidy * genome_size * average_base_pair_mass / avogadro

    def calculate(protein_intensity, histone_intensity, mw):
        """
        Calculate the copy number, moles, and weight of a protein.

        This function estimates the copy number, moles, and weight of a protein
        based on its intensity, histone intensity, and molecular weight (mw).

        @param protein_intensity (float): The intensity of the protein.
        @param histone_intensity (float): The summed intensity of histones.
        @param mw (float): The molecular weight of the protein.
        @return tuple: A tuple containing the calculated copy number, moles (in nmol),
        """

        copy = (protein_intensity / histone_intensity) * dna_mass * avogadro / mw
        # The number of moles is equal to the number of particles divided by Avogadro's constant
        moles = copy * 1e9 / avogadro  # unit nmol
        weight = moles * mw  # unit ng
        return tuple([copy, moles, weight])

    def proteomic_ruler(df):
        """
        Apply the proteomic ruler approach to calculate protein metrics for each condition.

        This method calculates the copy number, moles, weight, and concentration of proteins
        in a DataFrame by applying the proteomic ruler approach. It first computes the total
        intensity of histones and uses it to normalize protein intensities. The results are
        stored in new columns for each protein entry. The concentration is calculated based
        on the total weight and a given concentration per cell (cpc).

        @param df (pd.DataFrame): DataFrame containing protein data with normalized intensity and molecular weight.
        @return pd.DataFrame: Updated DataFrame with calculated protein metrics for each condition.
        """

        histone_intensity = df[df[PROTEIN_NAME].isin(histones_list)][NORM_INTENSITY].sum()
        histone_intensity = histone_intensity if histone_intensity > 0 else 1
        df[[COPYNUMBER, MOLES_NMOL, WEIGHT_NG]] = df.apply(
            lambda x: calculate(x[NORM_INTENSITY], histone_intensity, x[MOLECULARWEIGHT]),
            axis=1,
            result_type="expand",
        )
        volume = df[WEIGHT_NG].sum() * 1e-9 / cpc  # unit L
        df[CONCENTRATION_NM] = df[MOLES_NMOL] / volume  # unit nM
        return df

    res = res.groupby([CONDITION]).apply(proteomic_ruler)
    return res


def peptides_to_protein(
    fasta: str,
    peptides: str,
    enzyme: str,
    normalize: bool,
    min_aa: int,
    max_aa: int,
    tpa: bool,
    ruler: bool,
    ploidy: int,
    cpc: float,
    organism: str,
    output: str,
    verbose: bool,
    qc_report: str,
) -> None:
    """
    Compute IBAQ values for peptides and generate a QC report.

    This function processes peptide intensity data to compute IBAQ values,
    optionally normalizes the data, and calculates protein metrics such as
    weight and concentration using a proteomic ruler approach. It also
    generates a QC report with distribution plots if verbose mode is enabled.

    :param min_aa: Minimum number of amino acids to consider a peptide.
    :param max_aa: Maximum number of amino acids to consider a peptide.
    :param fasta: Fasta file used to perform the peptide identification.
    :param peptides: Peptide intensity file.
    :param enzyme: Enzyme used to digest the protein sample.
    :param normalize: use some basic normalization steps.
    :param output: output format containing the ibaq values.
    :param verbose: Print addition information.
    :param qc_report: PDF file to store multiple QC images.
    :return:
    """

    def get_average_nr_peptides_unique_bygroup(pdrow: Series) -> Series:
        """
        Calculate the average number of unique peptides per protein group.

        This function computes the average number of unique peptides for a given
        protein group by dividing the normalized intensity by the product of the
        group size and the average unique peptide count. If no proteins are found
        in the group or the sum of unique peptide counts is zero, it returns NaN.
        :param pdrow: Series containing the protein group data.
        :return: Series containing the average number of unique peptides per protein group.
        """

        nonlocal map_size
        proteins_list = pdrow.name[0].split(";")
        summ = 0
        for prot in proteins_list:
            summ += uniquepepcounts[prot]
        if len(proteins_list) > 0 and summ > 0:
            return pdrow.NormIntensity / map_size[pdrow.name] / (summ / len(proteins_list))
        # If there is no protein in the group, return np nan
        return np.nan  # type: ignore

    def get_protein_group_mw(group: str) -> float:
        """
        Calculate the molecular weight of a protein group.
        :param group: Protein group.
        :return: Molecular weight of the protein group.
        """
        mw_list = [mw_dict[i] for i in group.split(";")]
        return sum(mw_list)

    if peptides is None or fasta is None:
        raise ValueError("Fasta and peptides files are required")
    # load data
    data = pd.read_csv(peptides, sep=",")
    data[NORM_INTENSITY] = data[NORM_INTENSITY].astype("float")
    data = data.dropna(subset=[NORM_INTENSITY])
    data = data[data[NORM_INTENSITY] > 0]
    # get fasta info
    proteins = data[PROTEIN_NAME].unique().tolist()
    proteins = sum([i.split(";") for i in proteins], [])
    uniquepepcounts, mw_dict, found_proteins = extract_fasta(
        fasta, enzyme, proteins, min_aa, max_aa, tpa
    )
    data = data[data[PROTEIN_NAME].isin(found_proteins)]
    # data processing
    print(data.head())
    map_size = data.groupby([PROTEIN_NAME, SAMPLE_ID, CONDITION]).size().to_dict()
    res = pd.DataFrame(data.groupby([PROTEIN_NAME, SAMPLE_ID, CONDITION])[NORM_INTENSITY].sum())
    # ibaq
    res[IBAQ] = res.apply(get_average_nr_peptides_unique_bygroup, 1)
    res = res.reset_index()
    # normalize ibaq
    if normalize:
        res = normalize_ibaq(res)
        # Remove IBAQ_NORMALIZED NAN values
        res = res.dropna(subset=[IBAQ_NORMALIZED])
        plot_column = IBAQ_PPB
    else:
        # Remove IBAQ NAN values
        res = res.dropna(subset=[IBAQ])
        plot_column = IBAQ
    res = res.reset_index(drop=True)
    # tpa
    if tpa:
        res[MOLECULARWEIGHT] = res.apply(lambda x: get_protein_group_mw(x[PROTEIN_NAME]), axis=1)
        res[MOLECULARWEIGHT] = res[MOLECULARWEIGHT].fillna(1)
        res[MOLECULARWEIGHT] = res[MOLECULARWEIGHT].replace(0, 1)
        res[TPA] = res[NORM_INTENSITY] / res[MOLECULARWEIGHT]
    # calculate protein weight(ng) and concentration(nM)
    if ruler:
        if not ploidy or not cpc or not organism or not tpa:
            raise ValueError(
                "Ploidy, cpc and organism tpa are required for calculate protein weight(ng) and concentration(nM)"
            )
        res = calculate_weight_and_concentration(res, ploidy, cpc, organism, histones)
    # Print the distribution of the protein IBAQ values
    if verbose:
        plot_width = len(set(res[SAMPLE_ID])) * 0.5 + 10
        pdf = PdfPages(qc_report)
        density1 = plot_distributions(
            res,
            plot_column,
            SAMPLE_ID,
            log2=True,
            width=plot_width,
            title="{} Distribution".format(plot_column),
        )
        box1 = plot_box_plot(
            res,
            plot_column,
            SAMPLE_ID,
            log2=True,
            width=plot_width,
            title="{} Distribution".format(plot_column),
            violin=False,
        )
        pdf.savefig(density1)
        pdf.savefig(box1)
        if tpa:
            density2 = plot_distributions(
                res, TPA, SAMPLE_ID, log2=True, width=plot_width, title="TPA Distribution"
            )
            box2 = plot_box_plot(
                res,
                TPA,
                SAMPLE_ID,
                log2=True,
                width=plot_width,
                title="{} Distribution".format(TPA),
                violin=False,
            )
            pdf.savefig(density2)
            pdf.savefig(box2)
        if ruler:
            density3 = plot_distributions(
                res,
                COPYNUMBER,
                SAMPLE_ID,
                width=plot_width,
                log2=True,
                title="{} Distribution".format(COPYNUMBER),
            )
            box3 = plot_box_plot(
                res,
                COPYNUMBER,
                SAMPLE_ID,
                width=plot_width,
                log2=True,
                title="{} Distribution".format(COPYNUMBER),
                violin=False,
            )
            pdf.savefig(density3)
            pdf.savefig(box3)
            density4 = plot_distributions(
                res,
                CONCENTRATION_NM,
                SAMPLE_ID,
                width=plot_width,
                log2=True,
                title="{} Distribution".format(CONCENTRATION_NM),
            )
            box4 = plot_box_plot(
                res,
                CONCENTRATION_NM,
                SAMPLE_ID,
                width=plot_width,
                log2=True,
                title="{} Distribution".format(CONCENTRATION_NM),
                violin=False,
            )
            pdf.savefig(density4)
            pdf.savefig(box4)
        pdf.close()
    res.to_csv(output, sep="\t", index=False)
