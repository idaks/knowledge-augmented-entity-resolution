import numpy as np
import csv
import sys
import os
import re
import time

import pandas as pd
import pyarrow as pa 
import gc

import spacy

from collections import Counter


from tqdm import tqdm
from sherlock import helpers
from sherlock.deploy.model import SherlockModel
from sherlock.functional import *
from sherlock.features.paragraph_vectors import initialise_pretrained_model, initialise_nltk
from sherlock.features.preprocessing import (
    extract_features,
    convert_string_lists_to_lists,
    prepare_feature_extraction,
    # load_parquet_values,
)
from sherlock.features.word_embeddings import initialise_word_embeddings
# from preparator_text import *
# from preparators_general import *

class DKInjector:
    """Inject domain knowledge to the data entry pairs.

    Attributes:
        config: the task configuration
        name: the injector name
    """
    def __init__(self, config, name):
        self.config = config
        self.name = name
        self.initialize()

    def initialize(self):
        pass

    def transform(self, entry):
        return entry

    def transform_file(self, input_fn, out_fn, overwrite=False, prompt_type=1):
        """Transform all lines of a tsv file.

        Run the knowledge injector. If the output already exists, just return the file name.

        Args:
            input_fn (str): the input file name
            overwrite (bool, optional): if true, then overwrite any cached output

        Returns:
            str: the output file name
        """
        out_fn = input_fn + '.dk'
        if not os.path.exists(out_fn) or \
            os.stat(out_fn).st_size == 0 or overwrite:

            with open(out_fn, 'w') as fout:
                for line in tqdm(open(input_fn)):
                    LL = line.split('\t')
                    if len(LL) == 3:
                        entry0 = self.transform(LL[0])
                        entry1 = self.transform(LL[1])
                        fout.write(entry0 + '\t' + entry1 + '\t' + LL[2])
        return out_fn


class GeneralDKInjector(DKInjector):
    """The domain-knowledge injector for publication and business data.
    """
    def initialize(self):
        """Initialize spacy"""
        self.nlp = spacy.load('en_core_web_lg')

    def transform(self, entry):
        """Transform a data entry.

        Use NER to regconize the product-related named entities and
        mark them in the sequence. Normalize the numbers into the same format.

        Args:
            entry (str): the serialized data entry

        Returns:
            str: the transformed entry
        """
        res = ''
        doc = self.nlp(entry, disable=['tagger', 'parser'])
        ents = doc.ents
        start_indices = {}
        end_indices = {}

        for ent in ents:
            start, end, label = ent.start, ent.end, ent.label_
            if label in ['PERSON', 'ORG', 'LOC', 'PRODUCT', 'DATE', 'QUANTITY', 'TIME']:
                start_indices[start] = label
                end_indices[end] = label

        for idx, token in enumerate(doc):
            if idx in start_indices:
                res += start_indices[idx] + ' '

            # normalizing the numbers
            if token.like_num:
                try:
                    val = float(token.text)
                    if val == round(val):
                        res += '%d ' % (int(val))
                    else:
                        res += '%.2f ' % (val)
                except:
                    res += token.text + ' '
            elif len(token.text) >= 7 and \
                 any([ch.isdigit() for ch in token.text]):
                res += 'ID ' + token.text + ' '
            else:
                res += token.text + ' '
        return res.strip()


class EntityLinkingDKInjector(DKInjector):
    """The domain-knowledge injector for publication and business data.
    """
    def initialize(self):
        """Initialize EL model"""
        # load refined model here
        from refined.inference.processor import Refined
        print("Loading RefinED model...")
        self.refined = Refined.from_pretrained(model_name='wikipedia_model', 
                            entity_set="wikipedia",
                            data_dir="../data/refined/wikipedia/",
                            download_files=True,
                            use_precomputed_descriptions=True,
                            device="cuda:0",
        )

        self.log_path = 'output/refined_outputs.txt'
        self.log_file = open(self.log_path, 'w')

    def transform_file(self, input_fn, out_fn, overwrite=False, prompt_type=1):
        """Transform all lines of a tsv file.

        Run the knowledge injector. If the output already exists, just return the file name.

        Args:
            input_fn (str): the input file name
            overwrite (bool, optional): if true, then overwrite any cached output

        Returns:
            str: the output file name
        """
        # out_fn = input_fn
        # out_fn = input_fn + '.refined.dk'
        if not os.path.exists(out_fn) or \
            os.stat(out_fn).st_size == 0 or overwrite:

            with open(out_fn, 'w') as fout:
                print(f"writing EL results to: {out_fn}")
                for line in tqdm(open(input_fn)):
                    LL = line.split('\t')
                    if len(LL) == 3:
                        entry0 = self.transform(LL[0])
                        entry1 = self.transform(LL[1])
                        fout.write(entry0 + '\t' + entry1 + '\t' + LL[2])
        return out_fn

    def transform(self, entry):
        """Transform a data entry.

        Use NER to regconize the product-related named entities and
        mark them in the sequence. Normalize the numbers into the same format.

        Args:
            entry (str): the serialized data entry

        Returns:
            str: the transformed entry
        """

        # print(entry)
        # COL name VAL lg 24 ' lds4821ww semi integrated built in white dishwasher 
        # lds4821wh 
        # COL description VAL lg 24 ' lds4821ww semi integrated built in 
        # white dishwasher lds4821wh xl tall tub cleans up to 16 place settings at once 
        # adjustable upper rack lodecibel quiet operation senseclean wash system 4 wash 
        # cycles with 3 spray arms multi-level water direction slim direct drive motor 
        # semi-integrated electronic control panel white finish 
        # COL price VAL  
        # print([t.split('VAL ')[-1] for t in entry.split('COL ')][1:])

        cols = [t.split(' VAL')[0] for t in entry.split('COL ')][1:]
        values = [t.split('VAL ')[-1] for t in entry.split('COL ')][1:]
        # print(cols)

        valuesTagged = []
        # print(values)
        for entry in values:
            if len(entry.replace(' ', '')) > 0:
                # print(entry)
                # print(len(entry))
                # spans = self.refined.process_text(entry)
                spans = self.refined.process_text(entry)
                text = entry
                # print(spans)
                for i in range(len(spans)-1, -1, -1):
                    # ent_name, span, ent_type = spans[i]
                    span= spans[i]
                    # print(span.predicted_entity_types)
                    if len(span.predicted_entity_types) > 0:
                        spanType = span.predicted_entity_types[0][1]
                        # text = text[:span.start] + '<' + spanType + '>' + entry[span.start:span.start + span.ln] + '</' + spanType + '>' + entry[span.start + span.ln:]
                        text = text[:span.start] + entry[span.start:span.start + span.ln] + ' (' + spanType + ')' + entry[span.start + span.ln:]
                    else:
                        text = entry
                valuesTagged.append(text)
            else:
                valuesTagged.append("")
        
        res = ""
        for idx, col in enumerate(cols):
            res += "COL %s VAL %s "%(col, valuesTagged[idx])
        # print(res)
        self.log_file.write(res + '\n')
        return res.strip()
        # raise NotImplementedError
        

class SherlockDKInjector(DKInjector):
    """
    The domain-knowledge inferred by Sherlock
    Deep Learning system 

    """
    def initialize(self):

        """Initialize spacy"""
        # self.nlp = spacy.load('en_core_web_lg')
        
        helpers.download_data() # Downloading the raw data into ../data/.
        prepare_feature_extraction() # Preparing feature extraction by downloading 4 files ../sherlock/features/
        initialise_word_embeddings()
        initialise_pretrained_model(400) # 400 => dimension 
        initialise_nltk()

        # init sherlock
        self.model = SherlockModel()
        self.model.initialize_model_from_json(with_weights=True, model_id="sherlock")

        # print("sherlock loaded...")  # check how much memory it takes up... --> 14312 MiB
        # time.sleep(10)

    def sep_ds(self, ds):
        """
        Separate the combined and serialized dataset to the original datasets
        use this as the input for Sherlock
        """
        dict_prep = {}
        for inner_value in ds:
            # [(' title ', ' query optimization by predicate move-around '), (' authors ', ' inderpal singh mumick , alon y. levy , yehoshua sagiv '), (' venue ', ' vldb '), (' year ', ' 1994 \t')]
            for k, v in inner_value:
                col_name = k.strip()
                col_value = v.strip()
                dict_prep.setdefault(col_name, []).append(col_value)
        return pd.DataFrame(dict_prep)

    def create_input_ds(self, ds_f):
        # col_names_1 = []
        # col_names_2 = []
        ds_1 = []
        ds_2 = []
        # ds_3 = []
        tails = []
        for line_p in open(ds_f):
            pattern = re.compile(r'(COL|VAL)')
            line = line_p.rstrip()
            body = line[:-1]
            tail = line[-1]
            tails.append(int(tail))
            items = pattern.split(body)[1:]
            assert len(items) % 4 == 0
            pairs = []
            for i in range(len(items) // 4):
                pairs.append((items[i * 4 + 1], items[i * 4 + 3]))
            pair_1 = pairs[:len(pairs) // 2]
            pair_2 = pairs[len(pairs) // 2:]
            ds_1.append(pair_1)
            ds_2.append(pair_2)
        df_1 = self.sep_ds(ds_1)
        df_2 = self.sep_ds(ds_2)
        df_3 = pd.DataFrame({'flag': tails})
        return df_1, df_2, df_3

    def prev_transform(self, df, cols, new_df, predict_labels, prompt_type=1):
        """
        Before combining two datasets:
        Manually serialized the rows + inject predict labels 
        Save as a new DataFrame: new_df
        
        @params: prompt_type: different types of input 
        {
            0: COL <text>{col}</text> <tag>{predict_labels[i]}</tag> VAL {old_value} input for kbert soft position
            1: COL {col} {predict_labels} VAL {cell_value}
            2: COL {col} /{predict_labels} VAL {cell_value}
        }
        """
        for index, row in df.iterrows():
            for i,col in enumerate(cols):
                old_value = row[col]
                # prompt=1: space
                # prompt=2: slash
                # prompt=3: kbert
                if prompt_type==0:
                    new_value = f"COL <head>{col}</head> <tail>{predict_labels[i]}</tail> VAL {old_value}"
                elif prompt_type==1:
                    new_value = f"COL {col} {predict_labels[i]} VAL {old_value}"
                elif prompt_type==2:
                    new_value = f"COL {col} /{predict_labels[i]} VAL {old_value}"
                new_df.at[index, col] = new_value
                # .....new_df 
        return new_df


    def train_test_sherlock(self, temp_f, values):
        """
        Load train, val, test datasets (should be preprocessed)
        Initialize model using the "pretrained" model or by training one from scratch.
        => we use the pretrained model 
        Evaluate and analyse the model predictions.
        """
        # self.model.fit(X_train, y_train, X_validation, y_validation, model_id="sherlock")
        # print('Trained and saved new model.')
        # print(f'Finished at {datetime.now()}, took {datetime.now() - start} seconds')
        # predicted_labels = model.predict(X_test)
        # predicted_labels = np.array([x.lower() for x in predicted_labels])
        
        extract_features(
            temp_f,
            values
        )
        feature_vectors = pd.read_csv(temp_f, dtype=np.float32)
        predicted_labels = self.model.predict(feature_vectors, "sherlock")
        return predicted_labels

    def transform_file(self, input_fn, out_fn, overwrite=True, prompt_type=1):
        """Transform all lines of a tsv file.

        Run the knowledge injector. If the output already exists, just return the file name.

        Args:
            input_fn (str): the input file name
            overwrite (bool, optional): if true, then overwrite any cached output

        Returns:
            str: the output file name
        """
        # out_fn = input_fn + f'.prompt_type{prompt_type}.sherlock.dk'
        print(out_fn)
        if not os.path.exists(out_fn) or \
            os.stat(out_fn).st_size == 0 or overwrite:

            with open(out_fn, 'w') as fout:
                df1, df2, df3 = self.create_input_ds(input_fn) # the first dataset, the second dataset, and the flag
                # df1: the first dataset; df2: the second dataset; df3: the pairing result

                df1_trans = pd.Series(df1.to_numpy().T.tolist(), name="values").astype(str)
                df2_trans = pd.Series(df2.to_numpy().T.tolist(), name="values").astype(str)
                
                # Use Pretrained Sherlock Model to predict the column types 
                # returns: list of predicted labels: e.g., array(['person', 'city', 'address'], dtype=object)
                # then annotate each cell across the columns 
                predicted_labels_1 = self.train_test_sherlock("../temporary_1.csv", df1_trans)
                predicted_labels_2 = self.train_test_sherlock("../temporary_2.csv", df2_trans)

                cols_1 = list(df1.columns)
                annotate_df1 = pd.DataFrame(columns=cols_1) # embed first 
                df1_serialized = self.prev_transform(df1, cols_1, annotate_df1, predicted_labels_1, prompt_type)

                cols_2 = list(df2.columns)
                annotate_df2 = pd.DataFrame(columns=cols_2) # embed first 
                df2_serialized = self.prev_transform(df2, cols_2, annotate_df2, predicted_labels_2, prompt_type)

                assert len(df1_serialized) == len(df2_serialized)
                for i in range(len(df1_serialized)):
                    entry0 = ''
                    entry1 = ''
                    fir_row = df1_serialized.iloc[i]
                    entry0 += ' '.join(fir_row)
                    sec_row = df2_serialized.iloc[i]
                    entry1 += ' '.join(sec_row)
                    entry2 = int(df3.loc[i, 'flag'])
                    # out_row_list.append(list(fir_row)+list(sec_row)+[entry2])
                    fout.write(entry0 + '\t' + entry1 + '\t' + str(entry2) + '\n')
                    # print(f"{entry0} + '\t' + {entry1} + '\t' + {entry2}")
        return out_fn

