import math
import pandas as pd
import numpy as np
import pdb
from sklearn.preprocessing import MinMaxScaler

def truncate(num, digits):
    stepper = pow(10.0, digits)
    return math.trunc(num*stepper)/stepper

# create a differenced series
def difference(dataset, interval=1):
    diff = list()
    for i in range(interval, len(dataset)):
            value = dataset[i] - dataset[i - interval]
            diff.append(value)
    return Series(diff)

# invert differenced forecast
def inverse_difference(last_ob, value):
    return value + last_ob

def transform_group(group_df, max_duration, output_fields):
    group_df = group_df.reset_index().drop('input', axis=1)
    cols = group_df.columns
  
    padding = pd.DataFrame(np.zeros((max_duration-group_df.shape[0], group_df.shape[1]), dtype=int))
    padding.columns = cols
    for i in range(len(padding)):
        padding.loc[i, output_fields] = group_df.loc[group_df.shape[0]-1, output_fields]
    # pad the time series with 
    padded_group_df = pd.DataFrame(pd.np.row_stack([group_df, padding]))
    padded_group_df.columns = cols 
    return padded_group_df

def transform(df, input_fields, output_fields, train_percentage=0.7, count=-1):
    df['left_pwm'] = df['left_pwm'].apply(truncate, args=(3,))
    df['right_pwm'] = df['right_pwm'].apply(truncate, args=(3,))
    df['input'] = 'l_'+df['left_pwm'].map(str)+'_r_'+df['right_pwm'].map(str)
    df = df.set_index(['input'])
    df = df.iloc[:count, :]

    # normalize inputs
    input_scaler = MinMaxScaler(feature_range=(0, 1))
    output_scaler = MinMaxScaler(feature_range=(0, 1))
    df.loc[:,input_fields] = input_scaler.fit_transform(df.loc[:,input_fields])
    grouped = df.groupby(df.index)
    num_trials = len(grouped)

    for key, item in grouped:
        print(grouped.get_group(key), '\n\n')

    # store max duration of a trial
    max_duration = max(grouped['sim_time'].count())


    # the start time of every trial, used later to recover trajectories
    start_times = grouped.first()

    #df.loc[:,'sim_time'] = grouped.apply(lambda x: x.loc[:, ['sim_time']].diff().cumsum().fillna(0))
    # remove the bias of starting points in each trial
    df.loc[:, output_fields] = grouped.apply(
        lambda x: x.loc[:, output_fields] - start_times.loc[x.name].loc[output_fields])

    # normalize x, y, theta outputs
    df.loc[:, output_fields] = output_scaler.fit_transform(df.loc[:, output_fields])

    # create new data frame that is of (# of trials, max_duration dimenstion) 
    df = df.groupby(['input']).apply(lambda x: transform_group(x, max_duration, output_fields))

    # unstack time series to columns
    df = df.unstack(level=1)

    n_train = int(num_trials*train_percentage)
    train_data = df.iloc[:n_train, :]
    test_data = df.iloc[n_train:, :]

    p = len(input_fields)
    J = len(output_fields)

    train_trial_names = train_data.index
    test_trial_names = test_data.index

    X_train = train_data[input_fields].values.reshape(n_train, p, max_duration).transpose(0, 2, 1)
    X_test = test_data[input_fields].values.reshape(num_trials-n_train, p, max_duration).transpose(0, 2, 1)
    y_train = train_data[output_fields].values.reshape(n_train, J, max_duration).transpose(0, 2, 1)
    y_test = test_data[output_fields].values.reshape(num_trials-n_train, J, max_duration).transpose(0, 2, 1)
    # access trial of specific inputs with df.loc['INPUT_VALUES', :]
    return (X_train, X_test, y_train, y_test, train_trial_names, test_trial_names, output_scaler, start_times, max_duration)

def inverse_transform(predictions, target, start_times):
    # undo what transform function did, converting numpy array to pandas DF
    df = pd.DataFrame(predictions)
