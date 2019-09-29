from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import csv
import os
import time
import json
import numpy as np
import torch
import logging
from transformer import Constants
import copy

logger = logging.getLogger(__name__)

domains = ['restaurant', 'hotel', 'attraction', 'train', 'taxi', 'hospital', 'police', 'bus', 'booking', 'general']
functions = ['inform', 'request', 'recommend', 'book', 'select', 'sorry', 'none']
arguments = ['pricerange', 'id', 'address', 'postcode', 'type', 'food', 'phone', 'name', 'area', 'choice',
             'price', 'time', 'reference', 'none', 'parking', 'stars', 'internet', 'day', 'arriveby', 'departure',
             'destination', 'leaveat', 'duration', 'trainid', 'people', 'department', 'stay']

def get_batch(data_dir, option, tokenizer, act_tokenizer, max_seq_length):
    examples = []
    prev_sys = None
    num = 0

    if option == 'train':
        with open('{}/train.json'.format(data_dir)) as f:
            source = json.load(f)
            predicted_acts = None
    elif option == 'val':
        with open('{}/val.json'.format(data_dir)) as f:
            source = json.load(f)
        with open('{}/BERT_dev_prediction.json'.format(data_dir)) as f:
            predicted_acts = json.load(f)
        # predicted_acts = None
    else:
        with open('{}/test.json'.format(data_dir)) as f:
            source = json.load(f)
        with open('{}/BERT_test_prediction.json'.format(data_dir)) as f:
            predicted_acts = json.load(f)
        # predicted_acts = None

    logger.info("Loading total {} dialogs".format(len(source)))
    for num_dial, dialog_info in enumerate(source):
        hist = []
        hist_segment = []
        dialog_file = dialog_info['file']
        dialog = dialog_info['info']
        for turn_num, turn in enumerate(dialog):
            # user = [vocab[w] if w in vocab else vocab['<UNK>'] for w in turn['user'].split()]
            tokens = tokenizer.tokenize(turn['user'])
            query = copy.copy(tokens)
            if len(tokens) > max_seq_length - 2:
                query = query[:max_seq_length - 2]
            # if 'book' in tokens or 'booked' in tokens or 'booking' in tokens:
            segment_user = 1  # turn_num * 2 if turn_num * 2 < Constants.MAX_SEGMENT else Constants.MAX_SEGMENT - 1
            segment_sys = 2  # turn_num * 2 + 1 if turn_num * 2 + 1 < Constants.MAX_SEGMENT else Constants.MAX_SEGMENT - 1
            if len(hist) == 0:
                if len(tokens) > max_seq_length - 2:
                    tokens = tokens[:max_seq_length - 2]
                segment_ids = [segment_user] * len(tokens)
            else:
                # segment_ids = [0] * (len(hist) + 1) + [1] * len(tokens)
                segment_ids = hist_segment + [Constants.PAD] + [segment_user] * len(tokens)
                tokens = hist + [Constants.SEP_WORD] + tokens
                if len(tokens) > max_seq_length - 2:
                    tokens = tokens[-(max_seq_length - 2):]
                    segment_ids = segment_ids[-(max_seq_length - 2):]
            """
            template = tokenizer.tokenize(turn['template'])
            if len(template) > Constants.TEMPLATE_MAX_LEN:
                template = template[:Constants.TEMPLATE_MAX_LEN]
            template_ids = tokenizer.convert_tokens_to_ids(template)
            padded_template_ids = template_ids + [Constants.PAD] * (Constants.TEMPLATE_MAX_LEN - len(template_ids))
            """
            resp = [Constants.SOS_WORD] + tokenizer.tokenize(turn['sys']) + [Constants.EOS_WORD]

            if len(resp) > Constants.RESP_MAX_LEN:
                resp = resp[:Constants.RESP_MAX_LEN - 1] + [Constants.EOS_WORD]
            else:
                resp = resp + [Constants.PAD_WORD] * (Constants.RESP_MAX_LEN - len(resp))

            resp_inp_ids = tokenizer.convert_tokens_to_ids(resp[:-1])
            resp_out_ids = tokenizer.convert_tokens_to_ids(resp[1:])

            bs = [0] * len(Constants.belief_state)
            if turn['BS'] != "None":
                for domain in turn['BS']:
                    for key, value in turn['BS'][domain]:
                        bs[Constants.belief_state.index(domain + '-' + key)] = 1

            if turn['KB'] == 0:
                query_results = [1, 0, 0, 0]
            elif turn['KB'] == 2:
                query_results = [0, 1, 0, 0]
            elif turn['KB'] == 3:
                query_results = [0, 0, 1, 0]
            elif turn['KB'] >= 4:
                query_results = [0, 0, 0, 1]
            """          
            if turn_num == 0:
                query_results += [1, 0, 0, 0]
            elif turn_num == 1:
                query_results += [0, 1, 0, 0]
            elif turn_num == 2:
                query_results += [0, 0, 1, 0]         
            elif turn_num >= 3:
                query_results += [0, 0, 0, 1]
            """
            tokens = [Constants.CLS_WORD] + tokens + [Constants.SEP_WORD]
            query = [Constants.CLS_WORD] + query + [Constants.SEP_WORD]

            segment_ids = [Constants.PAD] + segment_ids + [Constants.PAD]

            input_ids = tokenizer.convert_tokens_to_ids(tokens)
            input_mask = [1] * len(input_ids)

            query_ids = tokenizer.convert_tokens_to_ids(query)
            query_mask = [1] * len(query_ids)
            query_segment_ids = [1] * len(query_mask)

            query_padding = [Constants.PAD] * (max_seq_length - len(query_ids))
            query_ids += query_padding
            query_mask += query_padding
            padded_query_segment_ids = query_segment_ids + query_padding

            padding = [Constants.PAD] * (max_seq_length - len(input_ids))
            input_ids += padding
            input_mask += padding
            padded_segment_ids = segment_ids + padding

            assert len(input_ids) == len(input_mask) == len(padded_segment_ids) == max_seq_length, \
                "length {}, {}, {}".format(len(input_ids), len(input_mask), len(segment_ids))

            act_vecs = [0] * len(Constants.act_ontology)
            if turn['act'] != "None":
                for w in turn['act']:
                    act_vecs[Constants.act_ontology.index(w)] = 1

            bert_act_seq=[]
            if predicted_acts is not None:
                bert_act_vecs = np.asarray(predicted_acts[dialog_file][str(turn_num)], 'int64')
                domain = []
                func = []
                arg = []
                for i in range(len(bert_act_vecs)):
                    if bert_act_vecs[i]>0:

                        if i<len(domains):
                            d=domains[i]
                            if d not in domain:
                                domain.append(d)
                        else:
                            i-=len(domains)
                            if i <len(functions):
                                f=functions[i]
                                if f not in func:
                                    func.append(f)
                            else:
                                i -= len(functions)
                                a=arguments[i]
                                if a not in arg:
                                    arg.append(a)

                bert_act_seq=sorted(domain)+sorted(func)+sorted(arg)


            if len(bert_act_seq) < Constants.ACT_MAX_LEN:
                bert_action_masks = [0] * len(bert_act_seq)
            else:
                bert_action_masks = [0] * (Constants.ACT_MAX_LEN - 1)
            bert_act_seq = [Constants.SOS_WORD] + bert_act_seq + [Constants.EOS_WORD]
            if len(bert_act_seq) > Constants.ACT_MAX_LEN:
                bert_act_seq = bert_act_seq[:Constants.ACT_MAX_LEN - 1] + [Constants.EOS_WORD]
            else:
                bert_act_seq = bert_act_seq + [Constants.PAD_WORD] * (Constants.ACT_MAX_LEN - len(bert_act_seq))
            bert_action_masks += [1] * (Constants.ACT_MAX_LEN - len(bert_action_masks) - 1)
            bert_act_seq = act_tokenizer.convert_tokens_to_ids(bert_act_seq[1:])



                # -----------------------------------------act preprocess----------------------------------------------------
            source = []
            for k, v in turn['source'].items():
                source.append(k.split('_')[1][:-1])
            user = tokenizer.tokenize(turn['user'])
            act_user_ids = user + source
            if len(act_user_ids) > max_seq_length:
                act_user_ids = act_user_ids[-max_seq_length:]
            action = [Constants.SOS_WORD] + turn['actseq'] + [Constants.EOS_WORD]
            if len(turn['actseq'])<Constants.ACT_MAX_LEN:
                action_masks=[0]*len(turn['actseq'])
            else:
                action_masks=[0]*(Constants.ACT_MAX_LEN-1)
            if len(action) > Constants.ACT_MAX_LEN:
                action = action[:Constants.ACT_MAX_LEN - 1] + [Constants.EOS_WORD]
            else:
                action = action + [Constants.PAD_WORD] * (Constants.ACT_MAX_LEN - len(action))
            action_masks+=[1]*(Constants.ACT_MAX_LEN - len(action_masks)-1)
            action_inp_ids = act_tokenizer.convert_tokens_to_ids(action[:-1])
            action_out_ids = act_tokenizer.convert_tokens_to_ids(action[1:])
            act_user_ids = tokenizer.convert_tokens_to_ids(act_user_ids)
            act_user_ids += [Constants.PAD] * (max_seq_length - len(act_user_ids))
            labels = [0] * Constants.act_len
            if turn['act']:
                for w in turn['act']:
                    acts = w.split('-')
                    acts = act_tokenizer.convert_tokens_to_ids(acts)
                    labels[acts[0] - 3] = 1

                    labels[acts[1] - 3] = 1

                    labels[acts[2] - 3] = 1
            else:
                acts = ['general', 'none']
                acts = act_tokenizer.convert_tokens_to_ids(acts)
                labels[acts[0] - 3] = 1

                labels[acts[1] - 3] = 1

            examples.append([input_ids, action_masks, padded_segment_ids, act_vecs, \
                             query_results, resp_inp_ids, resp_out_ids, bs, bert_act_seq, act_user_ids,
                             action_inp_ids, action_out_ids, labels, dialog_file])
            num += 1


            sys = tokenizer.tokenize(turn['sys'])
            if turn_num == 0:
                hist = tokens[1:-1] + [Constants.SEP_WORD] + sys
                hist_segment = segment_ids[1:-1] + [Constants.PAD] + [segment_sys] * len(sys)
            else:
                hist = hist + [Constants.SEP_WORD] + tokens[1:-1] + [Constants.SEP_WORD] + sys
                hist_segment = hist_segment + [Constants.PAD] + segment_ids[1:-1] + [Constants.PAD] + [
                    segment_sys] * len(sys)

    all_input_ids = torch.tensor([f[0] for f in examples], dtype=torch.long)
    action_masks = torch.tensor([f[1] for f in examples], dtype=torch.float32).byte()
    all_segment_ids = torch.tensor([f[2] for f in examples], dtype=torch.long)
    all_act_vecs = torch.tensor([f[3] for f in examples], dtype=torch.float32)
    all_query_results = torch.tensor([f[4] for f in examples], dtype=torch.float32)
    all_response_in = torch.tensor([f[5] for f in examples], dtype=torch.long)
    all_response_out = torch.tensor([f[6] for f in examples], dtype=torch.long)
    all_belief_state = torch.tensor([f[7] for f in examples], dtype=torch.float32)
    bert_act_seq = torch.tensor([f[8] for f in examples], dtype=torch.long)

    act_user_ids = torch.tensor([f[9] for f in examples], dtype=torch.long)
    action_inp_ids = torch.tensor([f[10] for f in examples], dtype=torch.long)
    action_out_ids = torch.tensor([f[11] for f in examples], dtype=torch.long)
    labels = torch.tensor([f[12] for f in examples], dtype=torch.float32)

    all_files = [f[13] for f in examples]
    # all_template_ids = torch.tensor([f[9] for f in examples], dtype=torch.long)

    return all_input_ids, action_masks, all_segment_ids, all_act_vecs, \
           all_query_results, all_response_in, all_response_out, all_belief_state, \
           bert_act_seq, act_user_ids, action_inp_ids, action_out_ids, labels, all_files