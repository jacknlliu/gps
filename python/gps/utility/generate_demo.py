""" This file generates for a point mass for 4 starting positions and a single goal position. """

import matplotlib as mpl
from mpl_toolkits.mplot3d import Axes3D

mpl.use('Qt4Agg')

import sys
import os
import os.path
import logging
import copy
import argparse
import time
import threading
import numpy as np
import scipy as sp
import scipy.io
import numpy.matlib
import random
from random import shuffle

# Add gps/python to path so that imports work.
sys.path.append('/'.join(str.split(__file__, '/')[:-2]))
from gps.agent.mjc.agent_mjc import AgentMuJoCo
from gps.utility.data_logger import DataLogger
from gps.utility.demo_utils import compute_distance
from gps.sample.sample_list import SampleList
from gps.algorithm.algorithm_utils import gauss_fit_joint_prior
from gps.proto.gps_pb2 import JOINT_ANGLES, JOINT_VELOCITIES, \
                END_EFFECTOR_POINTS, END_EFFECTOR_POINT_VELOCITIES, \
                END_EFFECTOR_POINT_JACOBIANS, ACTION, RGB_IMAGE, RGB_IMAGE_SIZE, \
                CONTEXT_IMAGE, CONTEXT_IMAGE_SIZE
from gps.algorithm.policy.lin_gauss_policy import LinearGaussianPolicy  # Maybe useful if we unpickle the file as controllers

LOGGER = logging.getLogger(__name__)

class GenDemo(object):
        """ Generator of demos. """
        def __init__(self, config):
            self._hyperparams = config
            self._conditions = config['common']['conditions']

            # if 'train_conditions' in config['common']:
            #       self._train_idx = config['common']['train_conditions']
            #       self._test_idx = config['common']['test_conditions']
            # else:
            #       self._train_idx = range(self._conditions)
            #       config['common']['train_conditions'] = config['common']['conditions']
            #       self._hyperparams=config
            #       self._test_idx = self._train_idx
            self._exp_dir = config['common']['demo_exp_dir']
            self._data_files_dir = config['common']['data_files_dir']
            self._algorithm_files_dir = config['common']['demo_controller_file']
            self.data_logger = DataLogger()

        def generate(self, demo_file):
            """
             Generate demos and save them in a file for experiment.
             Returns: None.
            """
            # Load the algorithm
            import pickle

            algorithm_file = self._algorithm_files_dir # This should give us the optimal controller. Maybe set to 'controller_itr_%02d.pkl' % itr_load will be better?
            # algorithm_file = self._exp_dir
            # algorithm_files = self._algorithm_files_dir
            # self.algorithms = [] # A list of neural nets.
            # for i in range(4):
            #       algorithm = pickle.load(open(algorithm_files[i]))
            #       self.algorithms.append(algorithm)
            self.algorithm = pickle.load(open(algorithm_file)) # Just one demo algorithm for now.
            if self.algorithm is None:
                print("Error: cannot find '%s.'" % algorithm_file)
                os._exit(1) # called instead of sys.exit(), since t
                # if algorithm is None:
                #       print("Error: cannot find '%s.'" % algorithm_file)
                #       os._exit(1) # called instead of sys.exit(), since t

            # Keep the initial states of the agent the sames as the demonstrations.
            if 'learning_from_prior' in self._hyperparams['algorithm']:
                self._learning = self._hyperparams['algorithm']['learning_from_prior'] # if the experiment is learning from prior experience
            else:
                self._learning = False
            agent_config = self._hyperparams['demo_agent']
            #if agent_config['type']==AgentMuJoCo and (agent_config['filename'] == './mjc_models/pr2_arm3d.xml' or \
            #            agent_config['filename'] == './mjc_models/reacher_img.xml') and not self._learning:
            #    agent_config['x0'] = self.algorithm._hyperparams['agent_x0']
            #    agent_config['pos_body_idx'] = self.algorithm._hyperparams['agent_pos_body_idx']
            #    agent_config['pos_body_offset'] = self.algorithm._hyperparams['agent_pos_body_offset']
            self.agent = agent_config['type'](agent_config)

            # Roll out the demonstrations from controllers
            var_mult = self._hyperparams['algorithm']['demo_var_mult']
            T = self.algorithm.T
            # T = self.algorithms[0].T
            demos = []
            demo_idx_conditions = []  # Stores conditions for each demo

            M = agent_config['conditions']
            N = self._hyperparams['algorithm']['num_demos']
            sampled_demo_conds = [random.randint(0, M-1) for i in xrange(M)]
            sampled_demos = []
            #if True: #not self._learning: # LG
            if True:
                controllers = {}

                # Store each controller under M conditions into controllers.
                for i in xrange(M):
                    controllers[i] = self.algorithm.cur[i].traj_distr
                controllers_var = copy.copy(controllers)
                for i in xrange(M):
                    # Increase controller variance.
                    controllers_var[i].chol_pol_covar *= var_mult
                    # Gather demos.
                    for j in xrange(N):
                        demo = self.agent.sample(
                            controllers_var[i], i,
                            verbose=1000, noisy=True, #(i < self.algorithm._hyperparams['demo_verbose']), noisy=True, # TODO
                            save = True
                        )
                        demos.append(demo)
                        demo_idx_conditions.append(i)
            else:
                all_pos_body_offsets = []
                # Extract the neural network policy.
                self.algorithm.num_policies = self.algorithm._hyperparams.get('num_policies', 1)
                for j in xrange(self.algorithm.num_policies):
                # for j in xrange(1):
                    if self.algorithm._hyperparams.get('multiple_policy', False):
                        pol = self.algorithm.policy_opts[j].policy
                    else:
                        pol = self.algorithm.policy_opt.policy
                    pol.chol_pol_covar *= var_mult

                    for i in range(M / self.algorithm.num_policies * j, M / self.algorithm.num_policies * (j + 1)):
                        # Gather demos.
                        dists = []
                        for k in xrange(N):
                            demo = self.agent.sample(
                                pol, i, # Should be changed back to controller if using linearization
                                verbose=100, noisy=True, #(i < self._hyperparams['verbose_trials']), noisy=True # TODO
                                ) # Add noise seems not working. TODO: figure out why
                            demos.append(demo)
                            demo_idx_conditions.append(i)
                            all_pos_body_offsets.append(agent_config['pos_body_offset'][i])
                    #demo_agent_config = self._hyperparams['real_demo_agent']
                    #demo_agent = demo_agent_config['type'](demo_agent_config)
                    #for m in xrange(demo_agent_config['conditions']):
                    #    demo = demo_agent.sample(
                    #        pol, m,
                    #        verbose=100, noisy=True, #(m < self._hyperparams['verbose_trials']), noisy=True)
                    #    demos.append(demo)
                    #    demo_idx_conditions.append(m)
                    #agent_config['pos_body_offset'].extend(demo_agent_config['pos_body_offset'])
            # Filter failed demos
            if agent_config.get('filter_demos', False): # USED FOR PR2
                target_position = agent_config['target_end_effector'][:3]
                dist_threshold = agent_config.get('success_upper_bound', 0.01)
                dists = compute_distance(target_position, SampleList(demos))
                failed_idx = []
                for i, distance in enumerate(dists):
                    distance = distance[-1]
                    if(distance > dist_threshold):
                        failed_idx.append(i)
                LOGGER.debug("Removing %d failed demos: %s", len(failed_idx), str(failed_idx))
                demos_filtered = [demo for (i, demo) in enumerate(demos) if i not in failed_idx]
                demo_idx_conditions = [cond for (i, cond) in enumerate(demo_idx_conditions) if i not in failed_idx]
                demos = demos_filtered
                shuffle(demos)
                demo_list = SampleList(demos)
                demo_store = {'demoX': demo_list.get_X(),
                              'demoU': demo_list.get_U(),
                              'demoO': demo_list.get_obs(),
                              'demoConditions': demo_idx_conditions}

            # Filter out worst (M - good_conds) demos.
            elif agent_config['type']==AgentMuJoCo and agent_config['filename'] == './mjc_models/pr2_arm3d.xml':
                target_position = agent_config['target_end_effector'][:3]
                dists_to_target = np.zeros(len(demos))
                good_indices = []
                failed_indices = []
                for i in xrange(len(demos)):
                    if type(agent_config['target_end_effector']) is list:
                        target_position = agent_config['target_end_effector'][i][:3]
                    else:
                        target_position = agent_config['target_end_effector'][:3]

                    #for j in xrange(N):
                    demo_end_effector = demos[i].get(END_EFFECTOR_POINTS)
                    # NOTE - there was a bug here!!!
                    # dists_to_target[i*N+j] = np.amin(np.sqrt(np.sum((demo_end_effector[:, :3] - target_position.reshape(1, -1))**2, axis = 1)), axis = 0)
                    # Just choose the last time step since it may become unstable after achieving the minimum point.
                    dists_to_target[i] = np.sqrt(np.sum((demo_end_effector[:, :3] - target_position.reshape(1, -1))**2, axis = 1))[-1]
                    # dists_to_target[k][i*N + j] = np.sqrt(np.sum((demo_end_effector[:, :3] - target_position.reshape(1, -1))**2, axis = 1))[-1]
                    if dists_to_target[i] >= agent_config['success_upper_bound']:
                        failed_indices.append(i)
                # good_indices = [i for i in xrange(M) if i not in failed_indices]
                import pdb; pdb.set_trace()
                good_indices = [i for i in xrange(len(demos)) if i not in failed_indices]
                self._hyperparams['algorithm']['demo_cond'] = len(good_indices)
                filtered_demos = []
                demo_conditions = []
                failed_conditions = []
                #exp_dir = self._data_files_dir.replace("data_files", "")
                exp_dir = self._data_files_dir
                with open(exp_dir + 'log.txt', 'a') as f:
                    f.write('\nThe demo conditions are: \n')
                for i in good_indices:
                    filtered_demos.append(demos[i])
                    demo_conditions.append(all_pos_body_offsets[i])
                    with open(exp_dir + 'log.txt', 'a') as f:
                        f.write('\n' + str(all_pos_body_offsets[i]) + '\n')
                with open(exp_dir + 'log.txt', 'a') as f:
                    f.write('\nThe failed badmm conditions are: \n')
                # for i in xrange(M):
                for i in xrange(len(demos)):
                    if i not in good_indices:
                        failed_conditions.append(all_pos_body_offsets[i])
                        with open(exp_dir + 'log.txt', 'a') as f:
                            f.write('\n' + str(all_pos_body_offsets[i]) + '\n')
                shuffle(filtered_demos)
                demo_list =  SampleList(filtered_demos)
                demo_store = {'demoX': demo_list.get_X(), 'demoU': demo_list.get_U(), 'demoO': demo_list.get_obs(), \
                                    'demo_conditions': demo_conditions, 'failed_conditions': failed_conditions}
                import matplotlib.pyplot as plt
                from matplotlib.patches import Rectangle

                plt.close()
                fig = plt.figure()
                ax = Axes3D(fig)
                demo_conditions_x = [demo_conditions[i][0] for i in xrange(len(demo_conditions))]
                demo_conditions_y = [demo_conditions[i][1] for i in xrange(len(demo_conditions))]
                demo_conditions_z = [demo_conditions[i][2] for i in xrange(len(demo_conditions))]
                failed_conditions_x = [failed_conditions[i][0] for i in xrange(len(failed_conditions))]
                failed_conditions_y = [failed_conditions[i][1] for i in xrange(len(failed_conditions))]
                failed_conditions_z = [failed_conditions[i][2] for i in xrange(len(failed_conditions))]
                # subplt = plt.subplot()
                ax.scatter(demo_conditions_x, demo_conditions_y, demo_conditions_z, c='g', marker='o')
                ax.scatter(failed_conditions_x, failed_conditions_y, failed_conditions_z, c='r', marker='x')
                ax.scatter([-0.05, -0.05, .05, .05], [-0.05, 0.05, -.05, .05], [-0.05, 0.05, .05, .05], c='b', marker='*')
                # subplt.plot(demo_conditions_x, demo_conditions_y, 'go')
                # subplt.plot(failed_conditions_x, failed_conditions_y, 'rx')
                # ax = plt.gca()
                # ax.add_patch(Rectangle((-0.1, -0.1), 0.2, 0.2, fill = False, edgecolor = 'blue'))
                # box = subplt.get_position()
                # subplt.set_position([box.x0, box.y0 + box.height * 0.1, box.width, box.height*0.9])
                # subplt.legend(['demo_cond', 'failed_badmm'], loc='upper center', bbox_to_anchor=(0.5, -0.05), \
                #                     shadow=True, ncol=2)
                box = ax.get_position()
                ax.set_position([box.x0, box.y0 + box.height * 0.1, box.width, box.height*0.9])
                ax.legend(['demo_cond', 'failed_badmm'], loc='upper center', bbox_to_anchor=(0.5, -0.05), \
                                    shadow=True, ncol=2)
                plt.title("Distribution of demo conditions")
                # plt.xlabel('width')
                # plt.ylabel('length')
                plt.savefig(self._data_files_dir + 'distribution_of_demo_conditions_MaxEnt_z_0.05.png')
                plt.close()
            elif agent_config['type']==AgentMuJoCo and 'reacher' in agent_config['filename']:
                dists = []; failed_indices = []
                success_thresh = 0.05
                for m in range(M):
                  target_position = agent_config['target_end_effector'][m][:3]
                  for i in range(N):
                      index = m*N + i
                      demo = demos[index]
                      demo_ee = demos[index].get(END_EFFECTOR_POINTS)
                      dists.append(np.min(np.sqrt(np.sum((demo_ee[:, :3] - target_position.reshape(1, -1))**2, axis = 1))))
                      if dists[index] >= success_thresh: #agent_config['success_upper_bound']:
                        failed_indices.append(index)
                good_indices = [i for i in xrange(len(demos)) if i not in failed_indices]
                self._hyperparams['algorithm']['demo_cond'] = len(good_indices)
                filtered_demos = []
                filtered_demo_conditions = []
                for i in good_indices:
                    filtered_demos.append(demos[i])
                    filtered_demo_conditions.append(demo_idx_conditions[i])

                print 'Num demos:', len(filtered_demos)
                #shuffle(filtered_demos)
                demo_list =  SampleList(filtered_demos)
                demo_store = {'demoX': demo_list.get_X(), 'demoU': demo_list.get_U(), 'demoO': demo_list.get_obs(),
                              'demoConditions': filtered_demo_conditions} #, \
            else:
                shuffle(demos)
                demo_list = SampleList(demos)
                demo_store = {'demoX': demo_list.get_X(), 'demoU': demo_list.get_U(), 'demoO': demo_list.get_obs()}
            # Save the demos.
            self.data_logger.pickle(
                demo_file,
                copy.copy(demo_store)
            )

        def linearize_policy(self, samples, cond):
            policy_prior = self.algorithms[cond]._hyperparams['policy_prior']
            init_policy_prior = policy_prior['type'](policy_prior)
            init_policy_prior._hyperparams['keep_samples'] = False
            dX, dU, T = self.algorithms[cond].dX, self.algorithms[cond].dU, self.algorithms[cond].T
            N = len(samples)
            X = samples.get_X()
            pol_mu, pol_sig = self.algorithms[cond].policy_opt.prob(samples.get_obs().copy())[:2]
            # Update the policy prior with collected samples
            init_policy_prior.update(SampleList([]), self.algorithms[cond].policy_opt, samples)
            # Collapse policy covariances. This is not really correct, but
            # it works fine so long as the policy covariance doesn't depend
            # on state.
            pol_sig = np.mean(pol_sig, axis=0)
            pol_info_pol_K = np.zeros((T, dU, dX))
            pol_info_pol_k = np.zeros((T, dU))
            pol_info_pol_S = np.zeros((T, dU, dU))
            pol_info_chol_pol_S = np.zeros((T, dU, dU))
            pol_info_inv_pol_S = np.empty_like(pol_info_chol_pol_S)
            # Estimate the policy linearization at each time step.
            for t in range(T):
                # Assemble diagonal weights matrix and data.
                dwts = (1.0 / N) * np.ones(N)
                Ts = X[:, t, :]
                Ps = pol_mu[:, t, :]
                Ys = np.concatenate((Ts, Ps), axis=1)
                # Obtain Normal-inverse-Wishart prior.
                mu0, Phi, mm, n0 = init_policy_prior.eval(Ts, Ps)
                sig_reg = np.zeros((dX+dU, dX+dU))
                # On the first time step, always slightly regularize covariance.
                if t == 0:
                    sig_reg[:dX, :dX] = 1e-8 * np.eye(dX)
                # Perform computation.
                pol_K, pol_k, pol_S = gauss_fit_joint_prior(Ys, mu0, Phi, mm, n0,
                                                                                                        dwts, dX, dU, sig_reg)
                pol_S += pol_sig[t, :, :]
                pol_info_pol_K[t, :, :], pol_info_pol_k[t, :] = pol_K, pol_k
                pol_info_pol_S[t, :, :], pol_info_chol_pol_S[t, :, :] = \
                        pol_S, sp.linalg.cholesky(pol_S)
                pol_info_inv_pol_S[t, :, :] = sp.linalg.solve(
                                                    pol_info_chol_pol_S[t, :, :],
                                                    np.linalg.solve(pol_info_chol_pol_S[t, :, :].T, np.eye(dU))
                                                    )
            return LinearGaussianPolicy(pol_info_pol_K, pol_info_pol_k, pol_info_pol_S, pol_info_chol_pol_S, \
                                                                            pol_info_inv_pol_S)

