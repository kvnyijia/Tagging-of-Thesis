#!/usr/bin/env python
# coding: utf-8
# Best F1 score  [0.6269430051813472, 25]


import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
#get_ipython().run_line_magic('matplotlib', 'inline')
import pickle, json, re, time

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.autograd import Variable
from torch.utils.data import Dataset, DataLoader
from torch.utils.tensorboard import SummaryWriter

from sklearn.utils import shuffle
from sklearn.model_selection import train_test_split

from tqdm import tqdm_notebook as tqdm
#from tqdm import tqdm
from tqdm import trange

from gensim.parsing import remove_stopwords
import time
tStart=time.time()

import os

CWD = os.getcwd()
if 'task1' not in CWD:
    CWD = os.path.join(CWD, 'task1')


# ### Hyperparameter logging and tuning
# For tuning best models, you may need to save the used hyperparameters.<br />
# The two cells below make the logging convenient.

# In[ ]:


### Helper function for hyperparameters logging
import configparser

def write_config(filename, with_time=False):
    config = configparser.ConfigParser()
    config['DEFAULT'] = {'embedding_dim': embedding_dim,
                         'hidden_dim': hidden_dim,
                         'learning_rate': learning_rate,
                         'max_epoch': max_epoch,
                         'batch_size': batch_size}
    
    if with_time == False:
        with open("{}.ini".format(filename), 'w') as configfile:
            config.write(configfile)
        return 'config'
    else:
        timestr = time.strftime("%Y%m%d_%H%M%S")
        filename = filename + '_' + timestr
        with open("{}.ini".format(filename), 'w') as configfile:
            config.write(configfile)
        return ( 'config' + timestr )


# In[ ]:


### Hyperparameters tuning
### Run this cell for renewing the hyperparameters

embedding_dim = 300
hidden_dim = 1000
learning_rate = 1e-5
max_epoch = 50
batch_size = 32 # 15 or 32 doesn't matter
num_layers=2
# write the hyperparameters into config.ini
#write_config(os.path.join(CWD,"config"))

# if you are lazy to rename the config file then uncomment the below line
config_fname = write_config(os.path.join(CWD,"config"), True)
# config_fname will be used when logging training scalar to tensorboard


# ### Dataset pre-processing

# In[ ]:


dataset = pd.read_csv( os.path.join(CWD,'data/task1_trainset.csv'), dtype=str)


# In[ ]:


dataset.head()


# In[ ]:


### Remove (current) redundant columns.

dataset.drop('Title',axis=1,inplace=True)
dataset.drop('Categories',axis=1,inplace=True)
dataset.drop('Created Date',axis=1, inplace=True)
dataset.drop('Authors',axis=1,inplace=True)
dataset['Abstract'] = dataset['Abstract'].str.lower()
#dataset['Task 1'] = dataset['Task 1'].str.lower()

from nltk.stem import WordNetLemmatizer 
lemmatizer = WordNetLemmatizer()

for i in range(len(dataset['Abstract'])):
    dataset['Abstract'][i] = lemmatizer.lemmatize(dataset['Abstract'][i])

#for i in range(len(dataset['Abstract'])):
#    dataset['Abstract'][i] = remove_stopwords(dataset['Abstract'][i])


# In[ ]:

# Three columns, Id, Abstract(lower case), Task1 
dataset.head()


# In[ ]:


# set test_size=0.1 for validation split
trainset, validset = train_test_split(dataset, test_size=0.1, random_state=42)

trainset.to_csv(os.path.join(CWD,'data/trainset.csv'),index=False)
validset.to_csv(os.path.join(CWD,'data/validset.csv'),index=False)


# In[ ]:


### Remove (current) redundant columns of the test set.

dataset = pd.read_csv(os.path.join(CWD,'data/task1_public_testset.csv'), dtype=str)
dataset.drop('Title',axis=1,inplace=True)
dataset.drop('Categories',axis=1,inplace=True)
dataset.drop('Created Date',axis=1, inplace=True)
dataset.drop('Authors',axis=1,inplace=True)
dataset['Abstract'] = dataset['Abstract'].str.lower()

for i in range(len(dataset['Abstract'])):
    dataset['Abstract'][i] = lemmatizer.lemmatize(dataset['Abstract'][i])

#for i in range(len(dataset['Abstract'])):
#    dataset['Abstract'][i] = remove_stopwords(dataset['Abstract'][i])

dataset.to_csv(os.path.join(CWD,'data/testset.csv'),index=False)


# ### Collect words and create the vocabulary set

# In[ ]:


from multiprocessing import Pool
from nltk.tokenize import word_tokenize

def collect_words(data_path, n_workers=4):
    df = pd.read_csv(data_path, dtype=str)

    # create a list for storing sentences
    sent_list = []
    for i in df.iterrows():
        # remove $$$ and append to sent_list
        sent_list += i[1]['Abstract'].split('$$$')

    # Put all list in the same chunk
    chunks = [
        ' '.join(sent_list[i:i + len(sent_list) // n_workers])
        for i in range(0, len(sent_list), len(sent_list) // n_workers)
    ]
    with Pool(n_workers) as pool:
        # word_tokenize for word-word separation
        chunks = pool.map_async(word_tokenize, chunks)

        # extract words
        words = set(sum(chunks.get(), []))
        
    return words

words = set()
words |= collect_words(os.path.join(CWD,'data/trainset.csv'))


# In[ ]:


PAD_TOKEN = 0
UNK_TOKEN = 1
word_dict = {'<pad>':PAD_TOKEN,'<unk>':UNK_TOKEN}

for word in words:
    word_dict[word]=len(word_dict) # len(word_dict)= 34966

with open(os.path.join(CWD,'dicitonary.pkl'),'wb') as f:
    pickle.dump(word_dict, f)


# ### Download Glove pretrained word embedding from web.
# 
# Link: http://nlp.stanford.edu/data/glove.6B.zip <br />
# It takes about 5 minutes for the download.
# 

# In[ ]:


import requests, zipfile, io
if not os.path.exists('glove'):
    os.mkdir('glove')
    r = requests.get('http://nlp.stanford.edu/data/glove.6B.zip')
    z = zipfile.ZipFile(io.BytesIO(r.content))
    z.extractall(path='glove')


# ### Parsing the GloVe word-embeddings file
# 
# Parse the unzipped file (a .txt file) to build an index that maps words (as strings) to their vector representation (as number vectors)

# In[ ]:


### Parsing the GloVe word-embeddings file
# Parse the unzipped file (a .txt file) to build an index that maps words (as strings) to their vector representation (as number vectors)

wordvector_path = 'glove/glove.6B.300d.txt'
embeddings_index = {}
f = open(wordvector_path)
for line in f:
    values = line.split()
    word = values[0] # glove ???????????? ?????? vocabulary
    coefs = np.asarray(values[1:], dtype='float32') # glove ??????vector
    embeddings_index[word] = coefs
f.close()
print('Found %s word vectors.' % len(embeddings_index))


# In[ ]:


### Preparing the GloVe word-embeddings matrix

max_words = len(word_dict)
embedding_matrix = np.zeros((max_words, embedding_dim)) # embedding_dim=100
for word, i in word_dict.items():
    #if i < max_words:
    embedding_vector = embeddings_index.get(word)
    if embedding_vector is not None:
        embedding_matrix[i] = embedding_vector
        # shape of embedding_matrix = (34966, 100) = (length of word_dict, embedding_dim)


# In[ ]:


embedding_matrix = torch.FloatTensor(embedding_matrix)


# ### Data Formatting
# ????????????????????????????????? data ???????????? batch????????????????????????????????????????????????????????? onehot vector???
# - `label_to_onehot(labels)`:  
#     ??? datasert ?????? label string ?????? onehot encoding vector???  
# - `sentence_to_indices(sentence, word_dict)`:  
#     ??????????????????????????? word ???????????????????????? index  
#     ex : 'i love ncku' -> $[1,2,3]$
# - `get_dataset(data_path, word_dict, n_workers=4)`:  
#     ??? dataset ??????
# - `preprocess_samples(dataset, word_dict)`:  
#     ???????????? input sentences ????????? data preprocessing  
# - `preprocess_sample(data, word_dict)`:  
#     ?????????????????? function ??????????????? 'Abstract' ?????? `$` ??????  
#     ?????? 'Label' ?????? onehot encoding vector???

# In[ ]:


def label_to_onehot(labels):
    """ Convert label to onehot .
        Args:
            labels (string): sentence's labels.
        Return:
            outputs (onehot list): sentence's onehot label.
    """
    label_dict = {'BACKGROUND': 0, 'OBJECTIVES':1, 'METHODS':2, 'RESULTS':3, 'CONCLUSIONS':4, 'OTHERS':5}
    onehot = [0,0,0,0,0,0]
    for l in labels.split('/'):
        onehot[label_dict[l]] = 1
    return onehot
        
def sentence_to_indices(sentence, word_dict):
    """ Convert sentence to its word indices.
    Args:
        sentence (str): One string.
    Return:
        indices (list of int): List of word indices.
    """
    return [word_dict.get(word,UNK_TOKEN) for word in word_tokenize(sentence)]

def get_dataset(data_path, word_dict, n_workers=4):
    """ Load data and return dataset for training and validating.

    Args:
        data_path (str): Path to the data.
    """
    dataset = pd.read_csv(data_path, dtype=str)

    results = [None] * n_workers
    with Pool(processes=n_workers) as pool:
        for i in range(n_workers):
            batch_start = (len(dataset) // n_workers) * i
            if i == n_workers - 1:
                batch_end = len(dataset)
            else:
                batch_end = (len(dataset) // n_workers) * (i + 1)
            
            batch = dataset[batch_start: batch_end]
            results[i] = pool.apply_async(preprocess_samples, args=(batch, word_dict))
            # results[i]???Abstact ????????????word??????word_dict???index, label ?????? on hot vector

        pool.close()
        pool.join()

    processed = []
    for result in results:
        processed += result.get()
    return processed

def preprocess_samples(dataset, word_dict):
    """ Worker function.

    Args:
        dataset (list of dict)
    Returns:
        list of processed dict.
    """
    processed = []
    for sample in tqdm(dataset.iterrows(), total=len(dataset)):
        processed.append(preprocess_sample(sample[1], word_dict))

    return processed

def preprocess_sample(data, word_dict):
    """
    Args:
        data (dict)
    Returns:
        dict
    """
    ## clean abstracts by removing $$$
    processed = {}
    processed['Abstract'] = [sentence_to_indices(sent, word_dict) for sent in data['Abstract'].split('$$$')]
    
    ## convert the labels into one-hot encoding
    if 'Task 1' in data:

        processed['Label'] = [label_to_onehot(label) for label in data['Task 1'].split(' ')] 
        # processed['Label'] is a 2D list
        
    return processed


# In[ ]:


print('[INFO] Start processing trainset...')
train = get_dataset(os.path.join(CWD,'data/trainset.csv'), word_dict, n_workers=4)
print('[INFO] Start processing validset...')
valid = get_dataset(os.path.join(CWD,'data/validset.csv'), word_dict, n_workers=4)
print('[INFO] Start processing testset...')
test = get_dataset(os.path.join(CWD,'data/testset.csv'), word_dict, n_workers=4)

def seperate_dict( the_list ):
    output=[]
    for row in  the_list: # row={'Abstract':[[],[],...], 'Label':[[],[],...]}
        #print('row=', row, '\n')
        #if ('Abstract' in row)and('Label' in row): # suspecious
        for i in range(len(row['Abstract']) ):
            new_dict={}
            #print('row= ', row, ' ')
            #print('in Abstact key= ', row['Abstract'][i], '\n in Label key= ', row['Label'][i], '\n')
            new_dict['Abstract']=[ row['Abstract'][i] ]

            if 'Label' in row:
                new_dict['Label']=[ row['Label'][i] ]

            output.append( new_dict.copy() )
    return output

train=seperate_dict(train)
valid=seperate_dict(valid)
test=seperate_dict(test)

# ### Create a dataset class for the abstract dataset
# `torch.utils.data.Dataset` is an abstract class representing a dataset.<br />Your custom dataset should inherit Dataset and override the following methods:
# 
# - `__len__` so that len(dataset) returns the size of the dataset.
# - `__getitem__` to support the indexing such that dataset[i] can be used to get i
# th sample
# - `collate_fn` Users may use customized collate_fn to achieve custom batching
#     - Here we pad sequences of various lengths (make same length of every single sentence)

# In[ ]:


class AbstractDataset(Dataset):
    def __init__(self, data, pad_idx, max_len = 64):
        self.data = data
        self.pad_idx = pad_idx
        self.max_len = max_len
        
    def __len__(self):
        return len(self.data)

    def __getitem__(self, index):
        return self.data[index]
        
    def collate_fn(self, datas): # datas = batch, len(datas)=batch_size
        # get max length in this batch
        max_sent = max([len(data['Abstract']) for data in datas])
        max_len = max([min(len(sentence), self.max_len) for data in datas for sentence in data['Abstract']])
        batch_abstract = []
        batch_label = []
        sent_len = []
        for data in datas: # a data is a row in trainset.csv, a datas is a number of batch_size of rows in trainset.csv
            # padding abstract to make them in same length
            pad_abstract = [] # pad_abstract is 1D now
            for sentence in data['Abstract']: # pad_abstract is 2D now
                if len(sentence) > max_len:
                    pad_abstract.append(sentence[:max_len])
                else:
                    pad_abstract.append(  sentence+[self.pad_idx]*( max_len-len(sentence) )  )
            sent_len.append(len(pad_abstract)) # how many sentences in this row
            pad_abstract.extend([[self.pad_idx]*max_len]*(max_sent-len(pad_abstract)))            
            batch_abstract.append(pad_abstract) # batch_abstract is 3D now
            '''
            print('len fo sentence', len(sentence), '\n') 
            print('len of pad_abstract', len(pad_abstract), '\n')
            print('len of batch_abstract', len(batch_abstract), '\n')
            print('-'*30)
            '''
            # gather labels
            if 'Label' in data:
                pad_label = data['Label']
                pad_label.extend([[0]*6]*(max_sent-len(pad_label)))
                batch_label.append(pad_label)
        '''
        print('In class AbstractDataset(Dataset): \n')
        print('len of batch_abstract', len(batch_abstract), '\n') # 16
        print('len of batch_label', len(batch_label), '\n') # 16
        print('len of sent_len', len(sent_len), '\n') # 16
        print('sent_len[2]=', sent_len[2], '\n' ) # lenght of sentence number 2 in this batch
        print('cols of batch_abstract[0]', len(batch_abstract[0]), ' ', 'cols of batch_label[0]', len(batch_label[0]), '\n')
        print('max_sent = ', str(max_sent), ' ', 'max_len = ', str(max_len), '\n')
        print('shape of torch.LongTensor(batch_abstract)', torch.LongTensor(batch_abstract).shape, ' shape of torch.FloatTensor(batch_label)', torch.FloatTensor(batch_label).shape, '\n')
        '''
        return torch.LongTensor(batch_abstract), torch.FloatTensor(batch_label), sent_len


# In[ ]:


trainData = AbstractDataset(train, PAD_TOKEN, max_len = 64)


# In[ ]:


trainData = AbstractDataset(train, PAD_TOKEN, max_len = 64)
validData = AbstractDataset(valid, PAD_TOKEN, max_len = 64)
testData = AbstractDataset(test, PAD_TOKEN, max_len = 64)

#print('type of trainData', type(trainData), '\n')
#print('type of validData', type(validData), '\n')
#print('type of testData', type(testData), '\n')


class RCNN(nn.Module):
    def __init__(self, batch_size, output_size, hidden_size, vocab_size, embedding_length, weights):
        super(RCNN, self).__init__()
        
        """
        Arguments
        ---------
        batch_size : Size of the batch which is same as the batch_size of the data returned by the TorchText BucketIterator
        output_size : 2 = (pos, neg)
        hidden_sie : Size of the hidden_state of the LSTM
        vocab_size : Size of the vocabulary containing unique words
        embedding_length : Embedding dimension of GloVe word embeddings
        weights : Pre-trained GloVe word_embeddings which we will use to create our word_embedding look-up table 
        
        """
        
        self.batch_size = batch_size
        self.output_size = output_size
        self.hidden_size = hidden_size
        self.vocab_size = vocab_size
        self.embedding_length = embedding_length
        
        self.word_embeddings = nn.Embedding(vocab_size, embedding_length)# Initializing the look-up table.
        self.word_embeddings.weight = nn.Parameter(weights, requires_grad=False) # Assigning the look-up table to the pre-trained GloVe word embedding.
        self.dropout = 0.8
        self.lstm = nn.LSTM(embedding_length, hidden_size, dropout=self.dropout, bidirectional=True, num_layers=num_layers)
        self.W2 = nn.Linear(2*hidden_size+embedding_length, hidden_size+embedding_length)

        self.l1 = nn.Linear(hidden_size+embedding_length, hidden_size)
        torch.nn.init.xavier_normal_(self.l1.weight)

        self.label = nn.Linear(hidden_size, output_size)
        
    def forward(self, input_sentence, batch_size=None):
    
        """ 
        Parameters
        ----------
        input_sentence: input_sentence of shape = (batch_size, num_sequences)
        batch_size : default = None. Used only for prediction on a single sentence after training (batch_size = 1)
        
        Returns
        -------
        Output of the linear layer containing logits for positive & negative class which receives its input as the final_hidden_state of the LSTM
        final_output.shape = (batch_size, output_size)
        
        """
        
        """
        
        The idea of the paper "Recurrent Convolutional Neural Networks for Text Classification" is that we pass the embedding vector
        of the text sequences through a bidirectional LSTM and then for each sequence, our final embedding vector is the concatenation of 
        its own GloVe embedding and the left and right contextual embedding which in bidirectional LSTM is same as the corresponding hidden
        state. This final embedding is passed through a linear layer which maps this long concatenated encoding vector back to the hidden_size
        vector. After this step, we use a max pooling layer across all sequences of texts. This converts any varying length text into a fixed
        dimension tensor of size (batch_size, hidden_size) and finally we map this to the output layer.
        """
        input = self.word_embeddings(input_sentence) # embedded input of shape = (batch_size, num_sequences, embedding_length)

        input=input.squeeze(1)

        input = input.permute(1, 0, 2) # input.size() = (num_sequences, batch_size, embedding_length)
        if batch_size is None:
            h_0 = Variable(torch.zeros(num_layers*2, self.batch_size, self.hidden_size).cuda()) # Initial hidden state of the LSTM
            c_0 = Variable(torch.zeros(num_layers*2, self.batch_size, self.hidden_size).cuda()) # Initial cell state of the LSTM
        else:
            h_0 = Variable(torch.zeros(num_layers*2, batch_size, self.hidden_size).cuda())
            c_0 = Variable(torch.zeros(num_layers*2, batch_size, self.hidden_size).cuda())

        output, (final_hidden_state, final_cell_state) = self.lstm(input, (h_0, c_0))
        
        final_encoding = torch.cat((output, input), 2).permute(1, 0, 2)
        y = self.W2(final_encoding)

        y=torch.relu(self.l1(y)) # y.size() = (batch_size, num_sequences, hidden_size)

        y = y.permute(0, 2, 1) # y.size() = (batch_size, hidden_size, num_sequences)
        y = F.max_pool1d(y, y.size()[2]) # y.size() = (batch_size, hidden_size, 1)
        y = y.squeeze(2)
        logits = self.label(y)

        logits=logits.unsqueeze(1)
        logits=torch.sigmoid(logits)
        
        return logits

device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')


# In[ ]:


### Helper functions for scoring
threshold=0.3 # 0.4, 62.1%, epoch 13.   0.3, 62.8%, 16. 
class F1():
    def __init__(self):
        self.threshold = threshold
        self.n_precision = 0
        self.n_recall = 0
        self.n_corrects = 0
        self.name = 'F1'

    def reset(self):
        self.n_precision = 0
        self.n_recall = 0
        self.n_corrects = 0

    def update(self, predicts, groundTruth):
        predicts = predicts > self.threshold
        self.n_precision += torch.sum(predicts).data.item()
        self.n_recall += torch.sum(groundTruth).data.item()
        self.n_corrects += torch.sum(groundTruth.type(torch.bool) * predicts).data.item()

    def get_score(self):
        recall = self.n_corrects / self.n_recall
        precision = self.n_corrects / (self.n_precision + 1e-20)
        return 2 * (recall * precision) / (recall + precision + 1e-20)

    def print_score(self):
        score = self.get_score()
        return '{:.5f}'.format(score)


# In[ ]:


def _run_epoch(epoch, mode):
    model.train(True)
    if mode=="train":
        description = 'Train'
        dataset = trainData
        shuffle = True
    else:
        description = 'Valid'
        dataset = validData
        shuffle = False
    dataloader = DataLoader(dataset=dataset,
                            batch_size=batch_size,
                            shuffle=shuffle,
                            collate_fn=dataset.collate_fn,
                            num_workers=8)

    trange = tqdm(enumerate(dataloader), total=len(dataloader), desc=description)
    loss = 0
    f1_score = F1()

    # from class AbstractDataset(Dataset) 
    for i, (x, y, sent_len) in trange: # x = torch.LongTensor(batch_abstract), y = torch.FloatTensor(batch_label), sent_len = sent_len

        # Butters
        #print('In _run_epoch, i=', str(i), ' ', 'shape of x', x.shape, ' ', 'shape of y', y.shape, ' ', 'len of sent_len', len(sent_len), '\n')
        if(x.size()[0] is not batch_size):
            continue
        o_labels, batch_loss = _run_iter(x,y)
        if mode=="train":
            opt.zero_grad()
            batch_loss.backward()
            opt.step()

        loss += batch_loss.item()
        f1_score.update(o_labels.cpu(), y)

        trange.set_postfix(
            loss=loss / (i + 1), f1=f1_score.print_score())
    
    if mode=="train":
        history['train'].append({'f1':f1_score.get_score(), 'loss':loss/ len(trange)})
        writer.add_scalar('Loss/train', loss/ len(trange), epoch)
        writer.add_scalar('F1_score/train', f1_score.get_score(), epoch)
    else:
        history['valid'].append({'f1':f1_score.get_score(), 'loss':loss/ len(trange)})
        writer.add_scalar('Loss/valid', loss/ len(trange), epoch)
        writer.add_scalar('F1_score/valid', f1_score.get_score(), epoch)
    trange.close()
    

def _run_iter(x,y):
    abstract = x.to(device)
    labels = y.to(device)
    #print('\n\n In _run_iter, ', 'shape of x', x.shape, ' ', 'shape of y', y.shape)
    o_labels = model(abstract)
    #print('The output shape: ', o_labels.shape, ' The label shape: ', labels.shape, '\n')
    l_loss = criteria(o_labels, labels)
    return o_labels, l_loss

def save(epoch):
    if not os.path.exists(os.path.join(CWD,'model_RCNN')):
        os.makedirs(os.path.join(CWD,'model_RCNN'))
    torch.save(model.state_dict(), os.path.join( CWD,'model_RCNN/model.pkl.'+str(epoch) ))
    with open( os.path.join( CWD,'model_RCNN/history.json'), 'w') as f:
        json.dump(history, f, indent=4)


# In[ ]:

# RCNN (batch_size, output_size, hidden_size, vocab_size, embedding_length, weights)
model = RCNN(batch_size, 6, hidden_dim, max_words, embedding_dim, embedding_matrix)

opt = torch.optim.AdamW(model.parameters(), lr=learning_rate)
criteria = torch.nn.BCELoss()
model.to(device)
history = {'train':[],'valid':[]}

## Tensorboard
## save path: test_experiment/
tf_path = os.path.join(CWD, 'test_experiment')
if not os.path.exists(tf_path):
    os.mkdir(tf_path)
writer = SummaryWriter(os.path.join(tf_path,config_fname))

for epoch in range(max_epoch):
    print('Epoch: {}'.format(epoch))
    _run_epoch(epoch, 'train')
    _run_epoch(epoch, 'valid')
    save(epoch)

# Plot the training results 
with open(os.path.join(CWD,'model_RCNN/history.json'), 'r') as f:
    history = json.loads(f.read())
    
train_loss = [l['loss'] for l in history['train']]
valid_loss = [l['loss'] for l in history['valid']]
train_f1 = [l['f1'] for l in history['train']]
valid_f1 = [l['f1'] for l in history['valid']]

plt.figure(figsize=(7,5))
plt.title('Loss')
plt.plot(train_loss, label='train')
plt.plot(valid_loss, label='valid')
plt.legend()
plt.show()
plt.savefig("Loss_RCNN.png")

plt.figure(figsize=(7,5))
plt.title('F1 Score')
plt.plot(train_f1, label='train')
plt.plot(valid_f1, label='valid')
plt.legend()
plt.show()
plt.savefig("F1_score_RCNN.png")

best_score, best_epoch=max([[l['f1'], idx] for idx, l in enumerate(history['valid'])])
print('best_score= ', best_score, ', best_epoch= ', best_epoch, '\n')
print('Best F1 score ', max([[l['f1'], idx] for idx, l in enumerate(history['valid'])]))


# In[ ]:


# This is the Prediction cell.

# fill the epoch of the lowest val_loss to best_model
best_model = best_epoch
model.load_state_dict(state_dict=torch.load(os.path.join(CWD,'model_RCNN/model.pkl.{}'.format(best_model))))
model.train(False)
# double ckeck the best_model_score
_run_epoch(1, 'valid')

# start testing
dataloader = DataLoader(dataset=testData,
                            batch_size=batch_size,
                            shuffle=False,
                            collate_fn=testData.collate_fn,
                            num_workers=8)
trange = tqdm(enumerate(dataloader), total=len(dataloader), desc='Predict')
prediction = []
#print('1 prediction= ', prediction,'\n')
for i, (x, y, sent_len) in trange:
    if(x.size()[0] is not batch_size):
        continue
    o_labels = model(x.to(device))
    #print('In Prediction Cell, o_labels= ', o_labels)
    o_labels = o_labels>threshold
    for idx, o_label in enumerate(o_labels):
        #print('In Prediction Cell:', '\n', 'sent_len= ', sent_len,'\n')
        #print('2 prediction= ', prediction,'\n')
        prediction.append(o_label[:sent_len[idx]].to('cpu'))
prediction = torch.cat(prediction).detach().numpy().astype(int)


# In[ ]:


### Helper function for creating a csv file following the submission format

def SubmitGenerator(prediction, sampleFile, public=True, filename='prediction.csv'):
    sample = pd.read_csv(sampleFile)
    submit = {}
    submit['order_id'] = list(sample.order_id.values)
    redundant = len(sample) - prediction.shape[0]
    if public:
        submit['BACKGROUND'] = list(prediction[:,0]) + [0]*redundant
        submit['OBJECTIVES'] = list(prediction[:,1]) + [0]*redundant
        submit['METHODS'] = list(prediction[:,2]) + [0]*redundant
        submit['RESULTS'] = list(prediction[:,3]) + [0]*redundant
        submit['CONCLUSIONS'] = list(prediction[:,4]) + [0]*redundant
        submit['OTHERS'] = list(prediction[:,5]) + [0]*redundant
    else:
        submit['BACKGROUND'] = [0]*redundant + list(prediction[:,0])
        submit['OBJECTIVES'] = [0]*redundant + list(prediction[:,1])
        submit['METHODS'] = [0]*redundant + list(prediction[:,2])
        submit['RESULTS'] = [0]*redundant + list(prediction[:,3])
        submit['CONCLUSIONS'] = [0]*redundant + list(prediction[:,4])
        submit['OTHERS'] = [0]*redundant + list(prediction[:,5])
    df = pd.DataFrame.from_dict(submit) 
    df.to_csv(filename,index=False)


# In[ ]:


### Output csv for submission

SubmitGenerator(prediction,
                os.path.join(CWD,'data/task1_sample_submission.csv'), 
                True, 
                os.path.join(CWD,'submission_RCNN.csv'))

#get_ipython().run_line_magic('tensorboard', '--logdir=task1/test_experiment')
tEnd=time.time()
print('Overall processing time: '+ str ( round( (tEnd-tStart)/60 , 3) )+' minutes' )