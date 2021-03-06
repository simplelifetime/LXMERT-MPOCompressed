# -*- coding: utf-8 -*-
"""
Truncate a matrix with mpo in a truncate number.
Date: 2020.11.16
@author: Gaozefeng

ACL 2021 version
Date: 2021.05.27
@author: Peiyu Liu
"""
import numpy as np
import random
import torch.nn as nn
import torch
import IPython
import time
seed = 1234
random.seed(seed)
np.random.seed(seed)


class MPO:
    def __init__(self, mpo_input_shape, mpo_output_shape, truncate_num, fix_rank=None):
        self.mpo_input_shape = mpo_input_shape
        self.mpo_output_shape = mpo_output_shape
        self.truncate_num = truncate_num
        self.num_dim = len(mpo_input_shape)
        self.mpo_ranks = self.compute_rank(truncate_num=None)
        if fix_rank:
            self.mpo_truncate_ranks = fix_rank
        else:
            self.mpo_truncate_ranks = self.compute_rank(
                truncate_num=self.truncate_num)  # 以前是没有用到self，那么无法通过外界设置而更改

    def compute_rank_position(self, s, truncate_num=None):
        """
        Calculate the rank position in MPO bond dimension
        :param s: target bond ,type = int, range in [1:len(mpo_input_shape-1)], r_0 = r_n = 1.
        :return:  target bond 's' real bond dimension.
        """
        rank_left = 1  # ranks_left: all the shape multiply in left of 's'.
        rank_right = 1  # ranks_right: all the shape multiply in right of 's'.
        for i in range(0, s):
            rank_left = rank_left * \
                self.mpo_input_shape[i] * self.mpo_output_shape[i]
        for i in range(s, self.num_dim):
            rank_right = rank_right * \
                self.mpo_input_shape[i] * self.mpo_output_shape[i]
        if truncate_num == None:
            min_rank = min(rank_left, rank_right)
        else:
            min_rank = min(int(self.truncate_num), rank_left, rank_right)
        return min_rank

    def compute_rank(self, truncate_num):
        """
        :param mpo_input_shape: the input mpo shape, type = list. [i0,i1,i2,...,i_(n-1)]
        :param truncate_num: the truncate number of mpo, type = int.
        :return:max bond dimension in every bond position, type = list, [r0,r1,r2,...,r_n],r0=r_n=1
        """
        bond_dims = [1 for i in range(self.num_dim + 1)]
        for i in range(1, self.num_dim):
            bond_dims[i] = self.compute_rank_position(i, truncate_num)
        return bond_dims

    def get_tensor_set(self, inp_matrix):
        """
        Calculate the left canonical of input matrix with a given mpo_input_shape
        :param inp_matrix: the input matrix
        :param mpo_input_shape:
        :return: a tensor with left canonical in input matrix
        """
        tensor_set = []
        res = inp_matrix
        #################################################################################
        # make M(m1,m2,...,mk, n1,n2,...,nk) to M(m1,n1,m2,n2,...,mk,nk)
        res = res.reshape(
            tuple(self.mpo_input_shape[:]) + tuple(self.mpo_output_shape[:]))
        self.index_permute = np.transpose(
            np.array(range(len(self.mpo_input_shape) + len(self.mpo_output_shape))).reshape((2, -1))).flatten()
        res = np.transpose(res, self.index_permute)
        #################################################################################
        for i in range(self.num_dim - 1):
            # Do the SVD operator
            res = res.reshape(
                [self.mpo_ranks[i] * self.mpo_input_shape[i] * self.mpo_output_shape[i], -1])
            u, lamda, v = np.linalg.svd(res, full_matrices=False)
            # The first tensor should be T1(r_i+1, m_i, n_i, r_i)
            u = u.reshape([self.mpo_ranks[i], self.mpo_input_shape[i],
                          self.mpo_output_shape[i], self.mpo_ranks[i+1]])
            tensor_set.append(u)
            res = np.dot(np.diag(lamda), v)
        res = res.reshape([self.mpo_ranks[self.num_dim-1], self.mpo_input_shape[self.num_dim-1],
                           self.mpo_output_shape[self.num_dim-1], self.mpo_ranks[self.num_dim]])
        tensor_set.append(res)
        return tensor_set

    def left_canonical(self, tensor_set):
        left_canonical_tensor = [0 for i in range(self.num_dim + 1)]
        mat = tensor_set[0]
        mat = mat.reshape(-1, mat.shape[3])
        u, lamda, v = np.linalg.svd(mat, full_matrices=False)
        left_canonical_tensor[1] = np.dot(np.diag(lamda), v)
        for i in range(1, self.num_dim-1):
            mat = np.tensordot(left_canonical_tensor[i], tensor_set[i], [1, 0])
            mat = mat.reshape(-1, mat.shape[-1])
            u, lamda, v = np.linalg.svd(mat, full_matrices=False)
            left_canonical_tensor[i+1] = np.dot(np.diag(lamda), v)
        return left_canonical_tensor

    def right_canonical(self, tensor_set):
        """
        Calculate the right tensor canonical for MPO format required
        :param left_tensor: the tensor_set output from function: left_canonical
        :return: the right_tensor_canonical format for calculate the mpo decomposition
        """
        right_canonical_tensor = [0 for i in range(self.num_dim + 1)]
        # print(tensor_set.shape)
        mat = tensor_set[self.num_dim - 1]
        mat = mat.reshape(mat.shape[0], -1)
        u, lamda, v = np.linalg.svd(mat, full_matrices=False)
        right_canonical_tensor[self.num_dim - 1] = np.dot(u, np.diag(lamda))

        for i in range(self.num_dim - 2, 0, -1):
            mat = np.tensordot(
                tensor_set[i], right_canonical_tensor[i + 1], [3, 0])
            mat = mat.reshape(mat.shape[0], -1)
            u, lamda, v = np.linalg.svd(mat, full_matrices=False)
            right_canonical_tensor[i] = np.dot(u, np.diag(lamda))
        return right_canonical_tensor

    def expectrum_normalization(self, lamda):
        """
        Do the lamda normalization for calculate the needed rank for MPO structure
        :param lamda: lamda parameter from left canonical
        :return:
        """
        norm_para = np.sum(lamda ** 2) ** (0.5)
        lamda_n = lamda / norm_para
        lamda_12 = lamda ** (-0.5)
        return lamda_n, np.diag(lamda_12)

    def gauge_aux_p_q(self, left_canonical_tensor, right_canonical_tensor):
        p = [0 for i in range(self.num_dim + 1)]
        q = [0 for i in range(self.num_dim + 1)]
        lamda_set = [0 for i in range(self.num_dim + 1)]
        lamda_set_value = [0 for i in range(self.num_dim + 1)]
        lamda_set[0] = np.ones([1, 1])
        lamda_set[-1] = np.ones([1, 1])
        for i in range(1, self.num_dim):
            mat = np.dot(left_canonical_tensor[i], right_canonical_tensor[i])
            # mat = right_canonical_tensor[i]
            u, lamda, v = np.linalg.svd(mat)
            lamda_n, lamda_l2 = self.expectrum_normalization(lamda)
            lamda_set[i] = lamda_n
            lamda_set_value[i] = lamda
            p[i] = np.dot(right_canonical_tensor[i], v.T)
            p[i] = np.dot(p[i], lamda_l2)
            q[i] = np.dot(lamda_l2, u.T)
            q[i] = np.dot(q[i], left_canonical_tensor[i])
        return p, q, lamda_set, lamda_set_value

    def mpo_canonical(self, tensor_set, p, q):
        tensor_set[0] = np.tensordot(tensor_set[0], p[1], [3, 0])
        tensor_set[-1] = np.tensordot(q[self.num_dim-1],
                                      tensor_set[-1], [1, 0])
        for i in range(1, self.num_dim-1):
            tensor_set[i] = np.tensordot(q[i], tensor_set[i], [1, 0])
            tensor_set[i] = np.tensordot(tensor_set[i], p[i+1], [3, 0])
        return tensor_set

    def truncated_tensor(self, tensor_set, step_train=False):
        """
        Get a untruncated tensor by mpo
        :param tensor_set: the input weight
        :return: a untruncated tensor_set by mpo
        """
        tensor_set = self.bi_canonical(tensor_set)
        mpo_trunc = self.mpo_truncate_ranks[:]
        for i in range(self.num_dim):
            if step_train:
                mask_noise = torch.ones_like(tensor_set[i])
            t = tensor_set[i]
            r_l = mpo_trunc[i]
            r_r = mpo_trunc[i + 1]
            # if isinstance(tensor_set[i], nn.parameter.Parameter):
            #     if step_train:
            #         # 在用的mask方法
            #         # mask_noise[r_l:, :, :, r_r:] = 0.0
            #         # 与truncate一致的mask方法
            #         mask_noise[r_l:, :, :, :] = 0.0
            #         mask_noise[:r_l, :, :, r_r:] = 0.0
            #         tensor_set[i].data = tensor_set[i].data * mask_noise
            #         # self.mask_noise.append(mask_noise)
            #         # self.zero_count += torch.nonzero(1.0 - mask_noise).shape[0]
            #     else:
            #         tensor_set[i].data = t[:r_l, :, :, :r_r]
            # else:
            #     assert "Check! tensor_set is not nn.parameter.Parameter"
            if isinstance(tensor_set[i], np.ndarray):
                if step_train:
                    # 在用的mask方法
                    # mask_noise[r_l:, :, :, r_r:] = 0.0
                    # 与truncate一致的mask方法
                    mask_noise[r_l:, :, :, :] = 0.0
                    mask_noise[:r_l, :, :, r_r:] = 0.0
                    tensor_set[i] = tensor_set[i] * mask_noise
                    # self.mask_noise.append(mask_noise)
                    # self.zero_count += torch.nonzero(1.0 - mask_noise).shape[0]
                else:
                    tensor_set[i] = t[:r_l, :, :, :r_r]
            else:
                assert "Check! tensor_set is not nn.parameter.Parameter"
        return tensor_set

    def compute_zero_count(self, tensor_set):
        # 每一次step_trunc后MPO实力化对象会保存自己的zero值数量，最后统计的时候只需要统计所有的实例的zero_count求和记得到所有的zero数量
        # for i in range(self.num_dim):
        #     zero_count += torch.nonzero(1.0 - self.mask_noise[i]).shape[0]
        # 修改2
        zero_count = 0
        mpo_trunc = self.mpo_truncate_ranks[:]
        for i in range(self.num_dim):
            mask_noise = torch.ones_like(tensor_set[i])
            r_l = mpo_trunc[i]
            r_r = mpo_trunc[i + 1]
            if isinstance(tensor_set[i], nn.parameter.Parameter):
                # 在用的mask方法
                # mask_noise[r_l:, :, :, r_r:] = 0.0
                # 与truncate一致的mask方法
                mask_noise[r_l:, :, :, :] = 0.0
                mask_noise[:r_l, :, :, r_r:] = 0.0
                tensor_set[i].data = tensor_set[i].data * mask_noise
                # self.mask_noise.append(mask_noise)
                zero_count += torch.nonzero(1.0 - mask_noise).shape[0]
        return zero_count

    def matrix2mpo(self, inp_matrix, cutoff=True):
        """
        Utilize the matrix to mpo format with or without cutoff
        :param inp_matrix: the input matrix, type=list
        :param cutoff: weather cut of not, type = bool
        :return: the truncated of not mps format of input matrix
        """
        tensor_set = self.get_tensor_set(inp_matrix)
        left_canonical_tensor = self.left_canonical(tensor_set)
        right_canonical_tensor = self.right_canonical(tensor_set)
        p, q, lamda_set, lamda_set_value = self.gauge_aux_p_q(
            left_canonical_tensor, right_canonical_tensor)
        tensor_set = self.mpo_canonical(tensor_set, p, q)
        if cutoff != False:
            tensor_set = self.truncated_tensor(tensor_set)
        return tensor_set, lamda_set, lamda_set_value

    def bi_canonical(self, tensor_set):
        left_canonical_tensor = self.left_canonical(tensor_set)
        right_canonical_tensor = self.right_canonical(tensor_set)
        p, q, _, _ = self.gauge_aux_p_q(
            left_canonical_tensor, right_canonical_tensor)
        tensor_set = self.mpo_canonical(tensor_set, p, q)

        return tensor_set

    def mpo2matrix(self, tensor_set):
        """
        shirnk the bond dimension to tranfer an mpo format to matrix format
        :param tensor_set: the input mpo format
        :return: the matrix format
        """
        t = tensor_set[0]
        # print(t.shape, tensor_set[1].shape)
        for i in range(1, self.num_dim):
            t = torch.tensordot(t, tensor_set[i], ([len(t.shape)-1], [0]))
        # Squeeze the first and the last 1 dimension
        t = t.squeeze(0)
        t = t.squeeze(-1)
        # Caculate the new index for mpo
        tmp1 = torch.tensor(range(len(self.mpo_output_shape))) * 2
        tmp2 = tmp1 + 1
        new_index = torch.cat((tmp1, tmp2), 0)
        # Transpose and reshape to output
        t = t.permute(tuple(new_index))
        t = t.reshape(torch.prod(torch.tensor(self.mpo_input_shape)),
                      torch.prod(torch.tensor(self.mpo_output_shape)))
        return t

    def calculate_total_mpo_param(self, cutoff=True):
        # print("use cutoff: ", cutoff)
        total_size = 0
        if cutoff:
            rank = self.mpo_truncate_ranks
        else:
            rank = self.mpo_ranks
        for i in range(len(self.mpo_input_shape)):
            total_size += rank[i] * self.mpo_input_shape[i] * \
                self.mpo_output_shape[i] * rank[i + 1]

        return total_size

    @staticmethod
    def test_difference(matrix1, matrix2):
        """
        we input an matrix , return the difference between those two matrix
        :param matrix:
        :return:
        """
        v = matrix1 - matrix2
        error = np.linalg.norm(v)
        return error

    def new_mpo2matrix(self, tensor_set):
        """
        shirnk the bond dimension to tranfer an mpo format to matrix format
        :param tensor_set: the input mpo format
        :return: the matrix format
        """
        t = tensor_set[0]
        # print(t.shape, tensor_set[1].shape)
        for i in range(1, self.num_dim):
            t = torch.tensordot(t, tensor_set[i], ([len(t.shape)-1], [0]))
        t = t.reshape(torch.prod(torch.tensor(self.mpo_input_shape)),
                      torch.prod(torch.tensor(self.mpo_output_shape)))
        return t


def FixAuxilaryTensorCalculateCentralTensor(tensor_set, New_matrix, New_central_in, New_central_out):
    """
    In put tensor set product by matrix2MPO, and New_matrix.
    return the central tensor when auxiliary tensor was fixed.
    We assumes n = 5
    """
    numpy_type = type(np.random.rand(2, 2))
    if type(New_matrix) == numpy_type:
        New_matrix = torch.from_numpy(New_matrix).cuda()
    else:
        New_matrix = New_matrix.cuda()
    if type(tensor_set[0]) == numpy_type:
        a = torch.from_numpy(tensor_set[0])
        b = torch.from_numpy(tensor_set[1])
        Ori_CentralTensor = torch.from_numpy(tensor_set[2])
        d = torch.from_numpy(tensor_set[3])
        e = torch.from_numpy(tensor_set[4])
    else:
        a = tensor_set[0]
        b = tensor_set[1]
        Ori_CentralTensor = tensor_set[2]
        d = tensor_set[3]
        e = tensor_set[4]
    left_basis = torch.tensordot(
        a, b, ([3], [0])).reshape(-1, Ori_CentralTensor.shape[0])
    right_basis = torch.tensordot(d, e, ([3], [0])).reshape(
        Ori_CentralTensor.shape[-1], -1)
    left_basis_inv = torch.inverse(left_basis)
    right_basis_inv = torch.inverse(right_basis)
    CentralTensor = torch.reshape(New_matrix, [
                                  Ori_CentralTensor.shape[0], New_central_in, New_central_out, Ori_CentralTensor.shape[3]])
    M_C = torch.tensordot(left_basis_inv, CentralTensor, ([1], [0]))
    M_C = torch.tensordot(M_C, right_basis_inv, ([3], [0]))
    return M_C


def FixCentralTensorCalculateAuxiliaryTensor(ori_tensor_set, ori_matrix, mpo_input_shape, mpo_output_shape, ranks):
    """
    In put tensor set product by matrix2MPO, and New_matrix.
    return the central tensor when auxiliary tensor was fixed.
    We assumes n = 5
    """

    ori_matrix = torch.from_numpy(ori_matrix).cuda() if type(
        ori_matrix) is np.ndarray else ori_matrix.cuda()

    if type(ori_tensor_set[0]) is np.ndarray:
        a = torch.from_numpy(ori_tensor_set[0]).cuda()
        b = torch.from_numpy(ori_tensor_set[1]).cuda()
        c = torch.from_numpy(ori_tensor_set[2]).cuda()
        d = torch.from_numpy(ori_tensor_set[3]).cuda()
        e = torch.from_numpy(ori_tensor_set[4]).cuda()
        f = torch.from_numpy(ori_tensor_set[5]).cuda()
    else:
        a = ori_tensor_set[0]
        b = ori_tensor_set[1]
        c = ori_tensor_set[2]
        d = ori_tensor_set[3]
        e = ori_tensor_set[4]
        f = ori_tensor_set[5]
    B = torch.tensordot(a, b, ([3], [0])).reshape(-1,
                                                  ranks[2])  # (i1j1i2j2,r2)
    C = c.reshape(-1, ranks[3])  # (r3,i3j3,r4), D = (r4,i4j4,r5)
    E = torch.tensordot(e, f, ([3], [0])).reshape(
        ranks[4], -1)  # (r4,i4j4i5j5,r6)
    D = d.reshape(ranks[3], -1)

    res = ori_matrix
    index_permute = np.transpose(
        np.array(range(len(mpo_input_shape) + len(mpo_output_shape))).reshape((2, -1))).flatten()
    B_inv = torch.inverse(B)
    E_inv = torch.inverse(E)
    D_inv = torch.inverse(D)

    res = res.reshape(tuple(mpo_input_shape[:]) + tuple(mpo_output_shape[:]))
    # res = np.transpose(res, index_permute).reshape(left_basis_inv.shape[1],-1)
    res = res.permute(tuple(index_permute)).reshape(B_inv.shape[1], -1)
    new_cdef = torch.matmul(B_inv, res).reshape(-1, E_inv.shape[0])
    new_cd = torch.matmul(new_cdef, E_inv).reshape(-1, ranks[3])
    new_c = torch.matmul(new_cd, D_inv).reshape(
        ranks[2], mpo_input_shape[2], mpo_output_shape[2], ranks[3])

    return new_c


if __name__ == "__main__":
    mpo_input_shape = [2, 3, 4, 5]
    mpo_output_shape = [4, 5, 6, 7]
    # mpo_ranks = [1,8,1]
    Data = np.random.rand(1, np.prod(mpo_input_shape),
                          np.prod(mpo_output_shape))

    mpo = MPO(mpo_input_shape=mpo_input_shape,
              mpo_output_shape=mpo_output_shape, truncate_num=100)
    print('input_modes is: ', mpo.mpo_input_shape)
    print('output_modes is: ', mpo.mpo_output_shape)
    print('max_bond_dims is: ', mpo.mpo_ranks)
    print('truncate_bond_dims is:', mpo.mpo_truncate_ranks)

    mpo_set, lamda_set = mpo.matrix2mpo(Data[0], cutoff=True)
    out = mpo.mpo2matrix(mpo_set)
    diff = mpo.test_difference(Data[0], out)
    print(diff, lamda_set[2])
