import dynet as dy
import random
from numpy import array
import numpy as np

EOS = "<EOS>"
characters = list("abcdefghijklmnopqrstuvwxyz ")
characters.append(EOS)
MB_SIZE = 3   #size of mini-batch

int2char = list(characters)
char2int = {c:i for i,c in enumerate(characters)}

VOCAB_SIZE = len(characters)

LSTM_NUM_OF_LAYERS = 2
EMBEDDINGS_SIZE = 32
STATE_SIZE = 32
ATTENTION_SIZE = 32

model = dy.Model()

enc_fwd_lstm = dy.LSTMBuilder(LSTM_NUM_OF_LAYERS, EMBEDDINGS_SIZE, STATE_SIZE, model)
enc_bwd_lstm = dy.LSTMBuilder(LSTM_NUM_OF_LAYERS, EMBEDDINGS_SIZE, STATE_SIZE, model)

dec_lstm = dy.LSTMBuilder(LSTM_NUM_OF_LAYERS, STATE_SIZE*2+EMBEDDINGS_SIZE, STATE_SIZE, model)

input_lookup = model.add_lookup_parameters((VOCAB_SIZE, EMBEDDINGS_SIZE))
attention_w1 = model.add_parameters( (ATTENTION_SIZE, STATE_SIZE*2))
attention_w2 = model.add_parameters( (ATTENTION_SIZE, STATE_SIZE*LSTM_NUM_OF_LAYERS*2))
attention_v = model.add_parameters( (1, ATTENTION_SIZE))
decoder_w = model.add_parameters( (VOCAB_SIZE, STATE_SIZE))
decoder_b = model.add_parameters( (VOCAB_SIZE))
output_lookup = model.add_lookup_parameters((VOCAB_SIZE, EMBEDDINGS_SIZE))


def embed_sentence(sentence):
    sentence = [EOS] + list(sentence) + [EOS]
    sentence = [char2int[c] for c in sentence]
    global input_lookup

    embedded_sentence = [input_lookup[char] for char in sentence]
    #embedded_sentence = [char for char in sentence]
    #print embedded_sentence

    return embedded_sentence

def embed_sentence_batch(sentence):
    sentence = [EOS] + list(sentence) + [EOS]
    sentence = [char2int[c] for c in sentence]
    global input_lookup

    #embedded_sentence = [input_lookup[char] for char in sentence]
    embedded_sentence = [char for char in sentence]
    #print embedded_sentence

    return embedded_sentence

def run_lstm(init_state, input_vecs):
    s = init_state

    out_vectors = []
    for vector in input_vecs:
        s = s.add_input(vector)
        out_vector = s.output()
        out_vectors.append(out_vector)
    return out_vectors

def run_lstm_batch(init_state, input_vec):
    s = init_state

    out_vectors = []

    for vector in input_vec:
        vectors =  np.array([vector,]* MB_SIZE).tolist()
        s = s.add_input(dy.lookup_batch(input_lookup,vectors))
        out_vector = s.output()
        out_vectors.append(out_vector)
    #print('out_vectors dim ',out_vectors)
    #print('out_vectors shape ',array(out_vectors[0].value()).shape)
    return out_vectors

def encode_sentence(enc_fwd_lstm, enc_bwd_lstm, sentence):
    sentence_rev = list(reversed(sentence))

    fwd_vectors = run_lstm(enc_fwd_lstm.initial_state(), sentence)
    bwd_vectors = run_lstm(enc_bwd_lstm.initial_state(), sentence_rev)
    bwd_vectors = list(reversed(bwd_vectors))
    vectors = [dy.concatenate(list(p)) for p in zip(fwd_vectors, bwd_vectors)]

    return vectors

def encode_sentence_batch(enc_fwd_lstm, enc_bwd_lstm, sentence):
    #print sentence
    sentence_rev = list(reversed(sentence))

    fwd_vectors = run_lstm_batch(enc_fwd_lstm.initial_state(), sentence)
    bwd_vectors = run_lstm_batch(enc_bwd_lstm.initial_state(), sentence_rev)
    #print bwd_vectors
    bwd_vectors = list(reversed(bwd_vectors))
    vectors = [dy.concatenate(list(p)) for p in zip(fwd_vectors, bwd_vectors)]

    return vectors

def attend(input_mat, state, w1dt):
    global attention_w2
    global attention_v
    w2 = dy.parameter(attention_w2)
    v = dy.parameter(attention_v)

    # input_mat: (encoder_state x seqlen) => input vecs concatenated as cols
    # w1dt: (attdim x seqlen)
    # w2dt: (attdim x attdim)
    w2dt = w2*dy.concatenate(list(state.s()))
    # att_weights: (seqlen,) row vector
    unnormalized = dy.transpose(v * dy.tanh(dy.colwise_add(w1dt, w2dt)))
    att_weights = dy.softmax(unnormalized)
    #print("att_weights val ",att_weights.value())
    #print("att_weights dim ",array(att_weights.value()).shape)
    # context: (encoder_state)
    context = input_mat * att_weights
    #print("context dim ",array(context.value()).shape)
    return context


def decode_batch(dec_lstm, vectors, output):
    output = [EOS] + list(output) + [EOS]
    output = [char2int[c] for c in output]
    #output = [c for c in output]
    output = array([output,]* MB_SIZE)
    output = np.transpose(output)
    #print('output ',output)
    w = dy.parameter(decoder_w)
    b = dy.parameter(decoder_b)
    w1 = dy.parameter(attention_w1)

    #print('len vectors ', len(vectors))
    #print('dim ', array(vectors[0].value()).shape)
    #print('dim ', vectors[0].value())
    input_mat = dy.concatenate_cols(vectors)
    #print("input_mat dim ", array(input_mat.value()).shape)
    w1dt = None

    last_output_embeddings = dy.lookup_batch(output_lookup,array([char2int[EOS],]*MB_SIZE))
    #last_output_embeddings = output_lookup[char2int[EOS]]
    #print("last_output_embeddings dim ",array(last_output_embeddings.value()).shape)
    s = dec_lstm.initial_state().add_input(dy.concatenate([dy.vecInput(STATE_SIZE*2), last_output_embeddings]))
    losses = []

    for chars in output:
        #print(chars)
        # w1dt can be computed and cached once for the entire decoding phase
        w1dt = w1dt or w1 * input_mat
        vector = dy.concatenate([attend(input_mat, s, w1dt), last_output_embeddings])
        s = s.add_input(vector)
        out_vector = w * s.output() + b
        #print(out_vector.value())
        loss = dy.pickneglogsoftmax_batch(out_vector, chars)
        #probs = dy.softmax(out_vector)
        last_output_embeddings = dy.lookup_batch(output_lookup,chars)
        #loss.append(-dy.log(dy.pick(probs, char)))
        losses.append(loss)
    return dy.sum_batches(dy.esum(losses))

def generate(in_seq, enc_fwd_lstm, enc_bwd_lstm, dec_lstm):
    embedded = embed_sentence(in_seq)
    encoded = encode_sentence(enc_fwd_lstm, enc_bwd_lstm, embedded)

    w = dy.parameter(decoder_w)
    b = dy.parameter(decoder_b)
    w1 = dy.parameter(attention_w1)
    input_mat = dy.concatenate_cols(encoded)
    w1dt = None

    last_output_embeddings = output_lookup[char2int[EOS]]
    s = dec_lstm.initial_state().add_input(dy.concatenate([dy.vecInput(STATE_SIZE * 2), last_output_embeddings]))

    out = ''
    count_EOS = 0
    for i in range(len(in_seq)*2):
        if count_EOS == 2: break
        # w1dt can be computed and cached once for the entire decoding phase
        w1dt = w1dt or w1 * input_mat
        vector = dy.concatenate([attend(input_mat, s, w1dt), last_output_embeddings])
        s = s.add_input(vector)
        out_vector = w * s.output() + b
        probs = dy.softmax(out_vector).vec_value()
        next_char = probs.index(max(probs))
        last_output_embeddings = output_lookup[next_char]
        if int2char[next_char] == EOS:
            count_EOS += 1
            continue

        out += int2char[next_char]
    return out

def get_loss_batch(input_sentence, output_sentence, enc_fwd_lstm, enc_bwd_lstm, dec_lstm):
    dy.renew_cg()
    embedded = embed_sentence_batch(input_sentence)
    encoded = encode_sentence_batch(enc_fwd_lstm, enc_bwd_lstm, embedded)
    return decode_batch(dec_lstm, encoded, output_sentence)

def train(model, sentence):
    trainer = dy.SimpleSGDTrainer(model)
    for i in range(600):
        loss = get_loss_batch(sentence, sentence, enc_fwd_lstm, enc_bwd_lstm, dec_lstm)
        #loss = get_loss(sentence, sentence, enc_fwd_lstm, enc_bwd_lstm, dec_lstm)
        loss_value = loss.value()
        loss.backward()
        trainer.update()
        if i % 20 == 0:
            print(loss_value)
            print(generate(sentence, enc_fwd_lstm, enc_bwd_lstm, dec_lstm))

train(model, "it is working")
