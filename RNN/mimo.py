import argparse
import os
import sys
import math
from itertools import product
import pdb
import json

import numpy as np
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
import pickle
from numpy import arctan2
from mpl_toolkits.mplot3d import Axes3D
from keras.models import Sequential, model_from_json
from keras.layers import Dense, Dropout, LSTM, SimpleRNN, Dropout, GRU
from keras.initializers import Identity, RandomNormal
from keras.optimizers import Adam
from sklearn.preprocessing import MinMaxScaler
from sklearn.metrics import mean_squared_error
from sklearn.externals import joblib

from visualize import visualize_3D
from transform import transform, input_fields, output_fields, others

fname = 'trial_1000.csv'

# network parameter
p = len(input_fields)
J = len(output_fields)
layers_dims = [p, 10, J, J]
#fname = 'trial_0_to_3dot5_step_0dot1.csv'

# TODOs
#   Hyperparmaters:
#       - dropout keep_prob
#       - Gradient clipping
#   Evaluation:
#       - stability (gradient visualization, gradient clipping)
#       - learning speed
#       - predict arbitrary length
def shape_it(X):
    return np.expand_dims(X.reshape((-1,1)),2)

def twoD2threeD(np_array):
    if len(np_array.shape) != 2:
        raise AssertionError('np_array must be 2 dimension')
    return np_array.reshape(1, np_array.shape[0], np_array.shape[1])

def convert_to_inference_model(original_model):
    original_model_json = original_model.to_json()
    inference_model_dict = json.loads(original_model_json)

    layers = inference_model_dict['config']['layers']
    for layer in layers:
        if 'stateful' in layer['config']:
            layer['config']['stateful'] = True

        if 'batch_input_shape' in layer['config']:
            layer['config']['batch_input_shape'][0] = 1
            layer['config']['batch_input_shape'][1] = None

    inference_model = model_from_json(json.dumps(inference_model_dict))
    inference_model.set_weights(original_model.get_weights())
    inference_model.reset_states()
    return inference_model

def predict_seq(model, X, output_scaler):
    # X is the input sequence (without ground truth previous prediction)
    #prevState = np.zeros((1, J))
    predictions = []
    for i in range(len(X)):
        state = twoD2threeD(X[i].reshape((1,-1)))
        prediction = model.predict(state)
        predictions.append(prediction.ravel())
        #prevState = prediction
    return output_scaler.inverse_transform(np.array(predictions))

def calc_error(model, X, y, output_scaler):
    # X, y are unnormalized 3D
    rmse = 0

    for i in range(len(X)):
        predictions = predict_seq(model, X[i], output_scaler)
        unnorm_y = output_scaler.inverse_transform(y[i])

        rmse += np.sqrt(mean_squared_error(y[i], predictions))
    return rmse/y.size

def save_obj(obj, name):
    with open(os.path.join(dirpath, name + '.pkl'), 'wb') as f:
        pickle.dump(obj, f, pickle.HIGHEST_PROTOCOL)

def load_obj(name):
    with open(os.path.join(dirpath, name + '.pkl'), 'rb') as f:
        return pickle.load(f)

def trim_to_batch_mult(arr, batch_size):
    return arr[:-(len(arr)%batch_size), :, :]

def make_model(model_params, weights=None):
    '''
        turn the stateless model used for training into a stateful one
        for one step prediction
    '''
    batch_size = model_params['batch_size']
    stateful = model_params['stateful']
    time_step = model_params['time_step']
    
    model = Sequential()
    model.add(Dense(p, batch_input_shape=(batch_size, time_step, p), name='input_layer'))
    model.add(Dense(layers_dims[1], activation='tanh', kernel_initializer=RandomNormal(stddev=np.sqrt(2./layers_dims[0])), name='second_layer'))
    model.add(Dropout(0.2))
    #model.add(Dense(10, batch_input_shape=(batch_size, max_duration,), activation='tanh', kernel_initializer=RandomNormal(stddev=np.sqrt(2./layers_dims[1])), name='third_layer'))
    #model.add(Dropout(0.7))
    model.add(Dense(J, activation='tanh', kernel_initializer=RandomNormal(stddev=np.sqrt(2./layers_dims[1])), name='hidden_layer'))
    model.add(GRU(J, name='dynamic_layer', return_sequences=True, activation='tanh', stateful=stateful))
    model.add(Dense(J))
    if weights:
        # override default weights
        model.set_weights(weights)
    optimizer = Adam(lr=1e-5)
    model.compile(loss='mean_squared_error', optimizer='adam')

    return model
    
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Get path to data directory')
    parser.add_argument('--datadir', required=True)
    args = parser.parse_args(sys.argv[1:])

    datadir = args.datadir
    if not os.path.isdir(datadir):
        print('invalid DATA_DIR (pass in as argument)')

    dirpath = os.path.abspath(os.path.join(datadir, fname.split('.')[0]))
    print('dirpath: ', dirpath)
    datafile = os.path.join(dirpath, fname)
    df = pd.read_csv(datafile, engine='python')

    X_train_fname = os.path.join(dirpath, 'X_train.npy')
    X_test_fname = os.path.join(dirpath, 'X_test.npy')
    y_train_fname = os.path.join(dirpath, 'y_train.npy')
    y_test_fname = os.path.join(dirpath, 'y_test.npy')
    input_scaler_fname = os.path.join(dirpath, 'input_scaler.pkl')
    if os.path.isfile(X_train_fname):
        X_train = np.load(os.path.join(dirpath, 'X_train.npy'), allow_pickle=True) 
        X_test = np.load(os.path.join(dirpath, 'X_test.npy'), allow_pickle=True)
        y_train = np.load(os.path.join(dirpath, 'y_train.npy'), allow_pickle=True)
        y_test = np.load(os.path.join(dirpath, 'y_test.npy'), allow_pickle=True)
        input_scaler = joblib.load(input_scaler_fname)
    else:
        X_train, X_test, y_train, y_test, input_scaler, output_scaler = transform(df, count=-1)

        np.save(X_train_fname, X_train)
        np.save(X_test_fname, X_test)
        np.save(y_train_fname, y_train)
        np.save(y_test_fname, y_test)
        joblib.dump(input_scaler, input_scaler_fname)

    batch_size = 32
    timestep = 5
    X_train = trim_to_batch_mult(X_train, batch_size)
    X_test = trim_to_batch_mult(X_test, batch_size)
    y_train = trim_to_batch_mult(y_train, batch_size)
    y_test = trim_to_batch_mult(y_test, batch_size)

    stateless_model_params = {
            'batch_size': batch_size,
            'stateful': False,
            'time_step': timestep,
        }

    model = make_model(stateless_model_params)
    iterations = 20
    epochs = 10
    # learning curver
    train_loss_history = []
    test_loss_history = []
  
    '''
    # for debug purposes
    _X_train = X_train[:4]
    _y_train = y_train[:4]
    _X_test = X_test[:4]
    _y_test = y_test[:4]
    plot_l = 2
    plot_w = 2
    # plot learning curve
    train_fig, train_axes = plt.subplots(plot_l, plot_w)
    test_fig, test_axes = plt.subplots(plot_l, plot_w)
    
    train_fig.title = 'train trials'
    test_fig.title = 'test trials'
    train_fig.show()
    test_fig.show()
    for it in range(iterations):
        model.fit(X_train, y_train, epochs=epochs, batch_size=batch_size, verbose=0, shuffle=False)

        train_loss_history.append(calc_error(model, X_train, y_train, output_scaler))
        test_loss_history.append(calc_error(model, X_test, y_test, output_scaler)) 

        for idx, (x, y) in enumerate(product(range(plot_l), range(plot_w))):
            train_axes[x, y].clear()
            test_axes[x, y].clear()
       
        for idx, (x, y) in enumerate(product(range(plot_l), range(plot_w))):
            train_predictions = model.predict(twoD2threeD(_X_train[plot_l*x+y])) 
            test_predictions = model.predict(twoD2threeD(_X_test[plot_l*x+y]))
            visualize_3D(twoD2threeD(_y_train[plot_l*x+y]), train_axes[x, y])
            visualize_3D(train_predictions, train_axes[x, y])

            visualize_3D(twoD2threeD(_y_test[plot_l*x+y]), test_axes[x, y])
            visualize_3D(test_predictions, test_axes[x, y])
    

    # for debug purposes
    n = 0
    _X_train = X_train[n]
    _y_train = output_scaler.inverse_transform(y_train[n])
    _X_test = X_test[n]
    _y_test = output_scaler.inverse_transform(y_test[n])
    # plot learning curve
    fig = plt.figure()
    ax1 = fig.add_subplot(121)
    ax2 = fig.add_subplot(122)
    fig.show()
    '''

    for it in range(iterations):
        print('iteration %d' % it) 
        model.fit(X_train, y_train, epochs=epochs, batch_size=batch_size, verbose=0, shuffle=False)
        '''
        # create a stateful model for prediction
        stateful_model = convert_to_inference_model(model)
        # predict on one trial at a time
        train_predictions = predict_seq(stateful_model, _X_train, output_scaler)
        test_predictions = predict_seq(stateful_model, _X_test, output_scaler)
    
        ax1.clear()
        ax2.clear()
        visualize_3D(twoD2threeD(_y_train), ax1, plt_arrow=True) 
        visualize_3D(twoD2threeD(train_predictions), ax2, plt_arrow=True)
        plt.draw()
        plt.pause(4)
        
        train_loss_history.append(calc_error(stateful_model, X_train, y_train, output_scaler))
        test_loss_history.append(calc_error(stateful_model, X_test, y_test, output_scaler))
        '''
        
        train_predictions = model.predict(X_train)
        test_predictions = model.predict(X_test)
        train_cost = np.mean((train_predictions-y_train)**2)
        test_cost = np.mean((test_predictions-y_test)**2)
        train_loss_history.append(train_cost)
        test_loss_history.append(test_cost)

        print('train_cost: %f' % train_cost)
        print('test_cost: %f' % test_cost)
    
    # examine results
    #train_predictions = model.predict(X_train, batch_size=batch_size)
    #test_predictions = model.predict(X_test, batch_size=batch_size)
   
    
    plt.figure()
    plt.title('RMSE of train and test dataset')
    it_range = range(0, iterations)
    plt.plot(it_range, train_loss_history)
    plt.plot(it_range, test_loss_history)
    plt.legend(['train', 'test'])
    plt.show()
