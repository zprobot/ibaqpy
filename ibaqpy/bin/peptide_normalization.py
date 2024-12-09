import pandas as pd
import os
import re
import numpy as np
import duckdb
from ibaqpy.bin.normalization_methods import normalize_run

from ibaqpy.bin.ibaqpy_commons import (
    BIOREPLICATE,
    TECHREPLICATE,
    CHANNEL,
    CONDITION,
    FRACTION,
    INTENSITY,
    NORM_INTENSITY,
    PEPTIDE_CANONICAL,
    PEPTIDE_CHARGE,
    PEPTIDE_SEQUENCE,
    PROTEIN_NAME,
    RUN,
    SAMPLE_ID,
    PARQUET_COLUMNS,
    TMT16plex,
    TMT11plex,
    TMT10plex,
    TMT6plex,
    ITRAQ4plex,
    ITRAQ8plex,
    parquet_map,
)


def parse_uniprot_accession(uniprot_id: str) -> str:
    """
    Parse the uniprot accession from the uniprot id in the form of
    tr|CONTAMINANT_Q3SX28|CONTAMINANT_TPM2_BOVIN and convert to CONTAMINANT_Q3SX28
    :param uniprot_id: uniprot id
    :return: uniprot accession
    """
    uniprot_list = uniprot_id.split(";")
    result_uniprot_list = []
    for accession in uniprot_list:
        if accession.count("|") == 2:
            accession = accession.split("|")[1]
        result_uniprot_list.append(accession)
    return ";".join(result_uniprot_list)


def get_canonical_peptide(peptide_sequence: str) -> str:
    """
    This function returns a peptide sequence without the modification information
    :param peptide_sequence: peptide sequence with mods
    :return: peptide sequence
    """
    clean_peptide = re.sub("[\(\[].*?[\)\]]", "", peptide_sequence)
    clean_peptide = clean_peptide.replace(".", "").replace("-", "")
    return clean_peptide


def analyse_sdrf(sdrf_path: str) -> tuple:
    """
    This function is aimed to parse SDRF and return four objects:
    1. sdrf_df: A dataframe with channels and references annoted.
    2. label: Label type of the experiment. LFQ, TMT or iTRAQ.
    3. sample_names: A list contains all sample names.
    4. choice: A dictionary caontains key-values between channel
        names and numbers.
    :param sdrf_path: File path of SDRF.
    :return:
    """
    sdrf_df = pd.read_csv(sdrf_path, sep="\t")
    sdrf_df.columns = [i.lower() for i in sdrf_df.columns]

    labels = set(sdrf_df["comment[label]"])
    # Determine label type
    label, choice = get_label(labels)
    if label == "TMT":
        choice_df = (
            pd.DataFrame.from_dict(choice, orient="index", columns=[CHANNEL])
            .reset_index()
            .rename(columns={"index": "comment[label]"})
        )
        sdrf_df = sdrf_df.merge(choice_df, on="comment[label]", how="left")
    elif label == "ITRAQ":
        choice_df = (
            pd.DataFrame.from_dict(choice, orient="index", columns=[CHANNEL])
            .reset_index()
            .rename(columns={"index": "comment[label]"})
        )
        sdrf_df = sdrf_df.merge(choice_df, on="comment[label]", how="left")
    sample_names = sdrf_df["source name"].unique().tolist()
    technical_repetitions = len(sdrf_df["comment[technical replicate]"].unique())

    return technical_repetitions, label, sample_names, choice


def get_label(labels: list) -> (str, dict):
    """Return label type and choice dict according to labels list.

    :param labels: Labels from SDRF.
    :return: Tuple contains label type and choice dict.
    """
    choice = None
    if len(labels) == 1:
        label = "LFQ"
    elif "TMT" in ",".join(labels) or "tmt" in ",".join(labels):
        if (
                len(labels) > 11
                or "TMT134N" in labels
                or "TMT133C" in labels
                or "TMT133N" in labels
                or "TMT132C" in labels
                or "TMT132N" in labels
        ):
            choice = TMT16plex
        elif len(labels) == 11 or "TMT131C" in labels:
            choice = TMT11plex
        elif len(labels) > 6:
            choice = TMT10plex
        else:
            choice = TMT6plex
        label = "TMT"
    elif "ITRAQ" in ",".join(labels) or "itraq" in ",".join(labels):
        if len(labels) > 4:
            choice = ITRAQ8plex
        else:
            choice = ITRAQ4plex
        label = "ITRAQ"
    else:
        exit("Warning: Only support label free, TMT and ITRAQ experiment!")
    return label, choice


def remove_contaminants_entrapments_decoys(
        dataset: pd.DataFrame, protein_field=PROTEIN_NAME
) -> pd.DataFrame:
    """
    This method reads a file with a list of contaminants and high abudant proteins and
    remove them from the dataset.
    :param dataset: Peptide intensity DataFrame
    :param protein_field: protein field
    :return: dataset with the filtered proteins
    """
    contaminants = []
    contaminants.append("CONTAMINANT")
    contaminants.append("ENTRAP")
    contaminants.append("DECOY")
    cregex = "|".join(contaminants)
    return dataset[~dataset[protein_field].str.contains(cregex)]


def remove_protein_by_ids(
        dataset: pd.DataFrame, protein_file: str, protein_field=PROTEIN_NAME
) -> pd.DataFrame:
    """
    This method reads a file with a list of contaminants and high abudant proteins and
    remove them from the dataset.
    :param dataset: Peptide intensity DataFrame
    :param protein_file: contaminants file
    :param protein_field: protein field
    :return: dataset with the filtered proteins
    """
    contaminants_reader = open(protein_file, "r")
    contaminants = contaminants_reader.read().split("\n")
    contaminants = [cont for cont in contaminants if cont.strip()]
    cregex = "|".join(contaminants)
    return dataset[~dataset[protein_field].str.contains(cregex)]


def parquet_common_process(
        data_df: pd.DataFrame, label: str, choice: dict
) -> pd.DataFrame:
    """
    Apply a common process on data.
    :param data_df: Feature data in dataframe.
    :param label: Label type of the experiment.
    :param choice: Choice dict for a label type.
    :return: Processed data.
    """

    data_df = data_df.rename(columns=parquet_map)
    data_df[PROTEIN_NAME] = data_df.apply(lambda x: ";".join(x[PROTEIN_NAME]), axis=1)
    if label == "LFQ":
        data_df.drop(CHANNEL, inplace=True, axis=1)
    else:
        data_df[CHANNEL] = data_df[CHANNEL].map(choice)

    return data_df


def data_common_process(data_df: pd.DataFrame, min_aa: int) -> pd.DataFrame:
    # Remove 0 intensity signals from the data
    data_df = data_df[data_df[INTENSITY] > 0]
    data_df = data_df[data_df["Condition"] != "Empty"]

    # Filter peptides with less amino acids than min_aa (default: 7)
    data_df.loc[:,'len'] = data_df[PEPTIDE_CANONICAL].apply(len)
    data_df = data_df[data_df['len']>=min_aa]
    data_df.drop(['len'],inplace=True,axis=1)
    data_df[PROTEIN_NAME] = data_df[PROTEIN_NAME].apply(parse_uniprot_accession)
    if FRACTION not in data_df.columns:
        data_df[FRACTION] = 1
    data_df[TECHREPLICATE] = data_df[RUN].str.split("_").str.get(1)
    data_df[TECHREPLICATE] = data_df[TECHREPLICATE].astype("int")
    data_df = data_df[
        [
            PROTEIN_NAME,
            PEPTIDE_SEQUENCE,
            PEPTIDE_CANONICAL,
            PEPTIDE_CHARGE,
            INTENSITY,
            CONDITION,
            TECHREPLICATE,
            BIOREPLICATE,
            FRACTION,
            SAMPLE_ID,
        ]
    ]
    data_df[CONDITION] = pd.Categorical(data_df[CONDITION])
    data_df[SAMPLE_ID] = pd.Categorical(data_df[SAMPLE_ID])

    return data_df


def merge_fractions(dataset: pd.DataFrame) -> pd.DataFrame:
    """
    Merge features across fractions.
    :param dataset: dataset including all properties
    :return:
    """
    dataset.dropna(subset=[NORM_INTENSITY], inplace=True)
    dataset = dataset.groupby(
        [
            PROTEIN_NAME,
            PEPTIDE_SEQUENCE,
            PEPTIDE_CANONICAL,
            PEPTIDE_CHARGE,
            CONDITION,
            BIOREPLICATE,
            TECHREPLICATE,
            SAMPLE_ID,
        ],
        observed=True,
    ).agg({NORM_INTENSITY: "max"})
    dataset.reset_index(inplace=True)
    return dataset


def get_peptidoform_normalize_intensities(
        dataset: pd.DataFrame, higher_intensity: bool = True
) -> pd.DataFrame:
    """
    Select the best peptidoform for the same sample and the same replicates. A peptidoform is the combination of
    a (PeptideSequence + Modifications) + Charge state.
    :param dataset: dataset including all properties
    :param higher_intensity: select based on normalize intensity, if false based on best scored peptide
    :return:
    """
    dataset.dropna(subset=[NORM_INTENSITY], inplace=True)
    if higher_intensity:
        dataset = dataset.loc[
            dataset.groupby(
                [PEPTIDE_SEQUENCE, PEPTIDE_CHARGE, SAMPLE_ID, CONDITION, BIOREPLICATE],
                observed=True,
            )[NORM_INTENSITY].idxmax()
        ]
    # else:
    #     dataset = dataset.loc[
    #         dataset.groupby(
    #             [PEPTIDE_SEQUENCE, PEPTIDE_CHARGE, SAMPLE_ID, CONDITION, BIOREPLICATE],
    #             observed=True,
    #         )[SEARCH_ENGINE].idxmax()
    #     ]
    dataset.reset_index(drop=True, inplace=True)
    return dataset


def sum_peptidoform_intensities(dataset: pd.DataFrame) -> pd.DataFrame:
    """
    Sum the peptidoform intensities for all peptidofrom across replicates of the same sample.
    :param dataset: Dataframe to be analyzed
    :return: dataframe with the intensities
    """
    dataset.dropna(subset=[NORM_INTENSITY], inplace=True)
    dataset = dataset[
        [
            PROTEIN_NAME,
            PEPTIDE_CANONICAL,
            SAMPLE_ID,
            BIOREPLICATE,
            CONDITION,
            NORM_INTENSITY,
        ]
    ]
    dataset.loc[:, "NormIntensity"] = dataset.groupby(
        [PROTEIN_NAME, PEPTIDE_CANONICAL, SAMPLE_ID, BIOREPLICATE, CONDITION],
        observed=True,
    )[NORM_INTENSITY].transform("sum")
    dataset = dataset.drop_duplicates()
    dataset.reset_index(inplace=True, drop=True)
    return dataset


class Feature:

    def __init__(self, database_path: str):
        if os.path.exists(database_path):
            self.parquet_db = duckdb.connect()
            self.parquet_db = self.parquet_db.execute(
                "CREATE VIEW parquet_db AS SELECT * FROM parquet_scan('{}')".format(
                    database_path
                )
            )
            self.samples = self.get_unique_samples()
        else:
            raise FileNotFoundError(f"the file {database_path} does not exist.")

    @property
    def experimental_inference(self) -> tuple:
        self.labels = self.get_unique_labels()
        self.label, self.choice = get_label(self.labels)
        self.technical_repetitions = self.get_unique_tec_reps()
        return len(self.technical_repetitions), self.label, self.samples, self.choice

    @property
    def low_frequency_peptides(self, percentage=0.2) -> tuple:
        """Return peptides with low frequency"""
        f_table = self.parquet_db.sql(
            """
                SELECT "sequence","pg_accessions",COUNT(DISTINCT sample_accession) as "count" from parquet_db
                GROUP BY "sequence","pg_accessions"
                """
        ).df()
        f_table.dropna(subset=["pg_accessions"], inplace=True)
        try:
            f_table["pg_accessions"] = f_table["pg_accessions"].apply(
                lambda x: x[0].split("|")[1]
            )
        except IndexError:
            f_table["pg_accessions"] = f_table["pg_accessions"].apply(
                lambda x: x[0]
            )
        except Exception as e:
            print(e)
            exit(
                "Some errors occurred when parsing pg_accessions column in feature parquet!"
            )
        f_table.set_index(["sequence", "pg_accessions"], inplace=True)
        f_table.drop(
            f_table[f_table["count"] >= (percentage * len(self.samples))].index,
            inplace=True,
        )
        f_table.reset_index(inplace=True)
        return tuple(zip(f_table["pg_accessions"], f_table["sequence"]))

    @staticmethod
    def csv2parquet(csv):
        parquet_path = os.path.splitext(csv)[0] + ".parquet"
        duckdb.read_csv(csv).to_parquet(parquet_path)

    @staticmethod
    def get_label(labels: list) -> (str, dict):
        """Return label type and choice dict according to labels list.

        :param labels: Labels from SDRF.
        :return: Tuple contains label type and choice dict.
        """
        choice = None
        if len(labels) == 1 and (
                "LABEL FREE" in ",".join(labels) or "label free" in ",".join(labels)
        ):
            label = "LFQ"
        elif "TMT" in ",".join(labels) or "tmt" in ",".join(labels):
            if (
                    len(labels) > 11
                    or "TMT134N" in labels
                    or "TMT133C" in labels
                    or "TMT133N" in labels
                    or "TMT132C" in labels
                    or "TMT132N" in labels
            ):
                choice = TMT16plex
            elif len(labels) == 11 or "TMT131C" in labels:
                choice = TMT11plex
            elif len(labels) > 6:
                choice = TMT10plex
            else:
                choice = TMT6plex
            label = "TMT"
        elif "ITRAQ" in ",".join(labels) or "itraq" in ",".join(labels):
            if len(labels) > 4:
                choice = ITRAQ8plex
            else:
                choice = ITRAQ4plex
            label = "ITRAQ"
        else:
            exit("Warning: Only support label free, TMT and ITRAQ experiment!")
        return label, choice

    def get_report_from_database(self, samples: list, columns: list = None):
        """
        This function loads the report from the duckdb database for a group of ms_runs.
        :param columns: A list of columns
        :param samples: A list of samples
        :return: The report
        """
        cols = ','.join(columns) if columns is not None else '*'
        database = self.parquet_db.sql(
            """SELECT {} FROM parquet_db WHERE sample_accession IN {}""".format(
                cols, tuple(samples)
            )
        )
        report = database.df()
        return report

    def iter_samples(self, file_num: int = 20, columns: list = None):
        """
        :params file_num: The number of files being processed at the same time (default 20)
        :yield: _description_
        """
        ref_list = [
            self.samples[i: i + file_num]
            for i in range(0, len(self.samples), file_num)
        ]
        for refs in ref_list:
            batch_df = self.get_report_from_database(refs, columns)
            yield refs, batch_df

    def get_unique_samples(self):
        """
        return: A list of samples.
        """
        unique = self.parquet_db.sql(
            "SELECT DISTINCT sample_accession FROM parquet_db"
        ).df()
        return unique["sample_accession"].tolist()

    def get_unique_labels(self):
        """
        return: A list of labels.
        """
        unique = self.parquet_db.sql(
            "SELECT DISTINCT channel FROM parquet_db"
        ).df()
        return unique["channel"].tolist()

    def get_unique_tec_reps(self):
        """
        return: A list of labels.
        """
        unique = self.parquet_db.sql("SELECT DISTINCT run FROM parquet_db").df()
        try:
            unique["run"] = unique["run"].str.split("_").str.get(1)
            unique["run"] = unique["run"].astype("int")
        except ValueError as e:
            print(e)
            exit(
                f"Some errors occurred when getting technical repetitions: {Exception}"
            )

        return unique["run"].tolist()

    def get_median_map(self):
        med_map = {}
        for _, batch_df in self.iter_samples(1000, ["sample_accession", "intensity"]):
            meds = batch_df.groupby(["sample_accession"])["intensity"].median()
            med_map.update(meds.to_dict())
        global_med = np.median([med for med in med_map.values()])
        for sample, med in med_map.items():
            med_map[sample] = med / global_med
        return med_map

    def get_report_condition_from_database(self, cons: list, columns: list = None):
        """
        This function loads the report from the duckdb database for a group of ms_runs.
        :param columns: A list of columns
        :param cons: A list of conditions in
        :return: The report
        """
        cols = ','.join(columns) if columns is not None else '*'
        database = self.parquet_db.sql(
            """SELECT {} FROM parquet_db WHERE condition IN {}""".format(
                cols, tuple(cons)
            )
        )
        report = database.df()
        return report

    def iter_conditions(self, conditions: int = 10, columns: list = None):
        condition_list = self.get_unique_conditions()
        ref_list = [
            condition_list[i: i + conditions]
            for i in range(0, len(condition_list), conditions)
        ]
        for refs in ref_list:
            batch_df = self.get_report_condition_from_database(refs, columns)
            yield refs, batch_df

    def get_unique_conditions(self):
        """
        return: A list of conditions.
        """
        unique = self.parquet_db.sql("SELECT DISTINCT condition FROM parquet_db").df()
        return unique["condition"].tolist()

    def get_median_map_to_condition(self):
        med_map = {}
        for cons, batch_df in self.iter_conditions(
                1000, ["condition", "sample_accession", "intensity"]
        ):
            for con in cons:
                meds = (
                    batch_df[batch_df["condition"] == con]
                    .groupby(["sample_accession"])["intensity"]
                    .median()
                )
                meds = meds / meds.mean()
                med_map[con] = meds.to_dict()
        return med_map


def peptide_normalization(
        parquet: str,
        sdrf: str,
        min_aa: int,
        min_unique: int,
        remove_ids: str,
        remove_decoy_contaminants: bool,
        remove_low_frequency_peptides: bool,
        output: str,
        skip_normalization: bool,
        nmethod: str,
        pnmethod: str,
        log2: bool,
        save_parquet: bool,
) -> None:
    """

    :param parquet: Parquet file with features
    :param sdrf: SDRF file
    :param min_aa: Min amino acids
    :param min_unique: Min of unique peptides
    :param remove_ids: Remove features for the given proteins
    :param remove_decoy_contaminants: Remove contaminants and entrapment
    :param remove_low_frequency_peptides: Remove low frecuency peptides
    :param output: Output file
    :param skip_normalization: Skip normalization
    :param nmethod: normalization method for features
    :param pnmethod: peptide normalization method
    :param log2: log intensities for features before normalizing
    :param save_parquet: Save to parque file.
    """
    if os.path.exists(output):
        raise FileExistsError("The output file already exists.")

    if parquet is None:
        raise FileNotFoundError("The file does not exist.")

    print("Loading data..")
    feature = Feature(parquet)
    if sdrf:
        technical_repetitions, label, sample_names, choice = analyse_sdrf(sdrf)
    else:
        technical_repetitions, label, sample_names, choice = feature.experimental_inference
    if remove_low_frequency_peptides:
        low_frequency_peptides = feature.low_frequency_peptides
    header = False
    if not skip_normalization and pnmethod == "globalMedian":
        med_map = feature.get_median_map()
    elif not skip_normalization and pnmethod == "conditionMedian":
        med_map = feature.get_median_map_to_condition()
    for samples, df in feature.iter_samples():
        df.dropna(subset=["pg_accessions"], inplace=True)
        for sample in samples:
            # Perform data preprocessing on every sample
            print(f"{str(sample).upper()}: Data preprocessing...")
            dataset_df = df[df["sample_accession"] == sample].copy()
            # Step1: Parse the identifier of proteins and retain only unique peptides.
            dataset_df = dataset_df[dataset_df["unique"] == 1]
            dataset_df = dataset_df[PARQUET_COLUMNS]
            dataset_df = parquet_common_process(dataset_df, label, choice)
            # Step2: Remove lines where intensity or study condition is empty.
            # Step3: Filter peptides with less amino acids than min_aa.
            dataset_df = data_common_process(dataset_df, min_aa)
            # Step4: Delete low-confidence proteins.
            dataset_df = dataset_df.groupby(PROTEIN_NAME).filter(
                lambda x: len(set(x[PEPTIDE_CANONICAL])) >= min_unique
            )
            # Step5: Filter decoy, contaminants, entrapment
            if remove_decoy_contaminants:
                dataset_df = remove_contaminants_entrapments_decoys(dataset_df)
            # Step6: Filter user-specified proteins
            if remove_ids is not None:
                dataset_df = remove_protein_by_ids(dataset_df, remove_ids)
            dataset_df.rename(columns={INTENSITY: NORM_INTENSITY}, inplace=True)
            # Step7: Normalize at feature level between ms runs (technical repetitions)
            if (
                    not skip_normalization
                    and nmethod != "none"
                    and technical_repetitions > 1
            ):
                print(f"{str(sample).upper()}: Normalize intensities of features.. ")
                dataset_df = normalize_run(dataset_df, technical_repetitions, nmethod)
                print(
                    f"{str(sample).upper()}: Number of features after normalization: {len(dataset_df.index)}"
                )
            # Step8: Merge peptidoforms across fractions and technical repetitions
            dataset_df = get_peptidoform_normalize_intensities(dataset_df)
            print(
                f"{str(sample).upper()}: Number of peptides after peptidofrom selection: {len(dataset_df.index)}"
            )
            if len(dataset_df[FRACTION].unique().tolist()) > 1:
                print(f"{str(sample).upper()}: Merge features across fractions.. ")
                dataset_df = merge_fractions(dataset_df)
                print(
                    f"{str(sample).upper()}: Number of features after merging fractions: {len(dataset_df.index)}"
                )
            # Step9: Normalize the data.
            if not skip_normalization:
                if pnmethod == "globalMedian":
                    dataset_df.loc[:, NORM_INTENSITY] = (
                            dataset_df[NORM_INTENSITY] / med_map[sample]
                    )
                elif pnmethod == "conditionMedian":
                    con = dataset_df[CONDITION].unique()[0]
                    dataset_df.loc[:, NORM_INTENSITY] = (
                            dataset_df[NORM_INTENSITY] / med_map[con][sample]
                    )
            
            # Step10: Remove peptides with low frequency.
            if remove_low_frequency_peptides and len(sample_names) > 1:
                dataset_df.set_index(
                    [PROTEIN_NAME, PEPTIDE_CANONICAL], drop=True, inplace=True
                )
                dataset_df = dataset_df[
                    ~dataset_df.index.isin(low_frequency_peptides)
                ].reset_index()
                print(
                    f"{str(sample).upper()}: Peptides after remove low frequency peptides: {len(dataset_df.index)}"
                )

            # Step11: Assembly peptidoforms to peptides.
            print(f"{str(sample).upper()}: Sum all peptidoforms per Sample...")
            dataset_df = sum_peptidoform_intensities(dataset_df)
            print(
                f"{str(sample).upper()}: Number of peptides after selection: {len(dataset_df.index)}"
            )
            # Step12: Intensity transformation to log.
            if log2:
                dataset_df[NORM_INTENSITY] = np.log2(dataset_df[NORM_INTENSITY])

            print(f"{str(sample).upper()}: Save the normalized peptide intensities...")
            if header:
                dataset_df.to_csv(output, index=False, header=False, mode="a+")
            else:
                dataset_df.to_csv(output, index=False)
                header = True

    if save_parquet:
        feature.csv2parquet(output)
