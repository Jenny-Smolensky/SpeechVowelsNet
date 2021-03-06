# Modified by Jenny Smolensky & Almog Gueta
# __author__ = 'YaelSegal & TzeviyaFuchs'
import torch
import numpy as np

import Datasets
import utils
import random

# NUM_CLASSES = 1000
GAP_THRESH = 0.01  # MINIMUM GAP TO SEPARATE TWO IDENTICLE WORDS
SR = 16000

class TrainSpeechYolo:
    @staticmethod
    def train(train_loader, model, loss_func, config_dict, optimizer, epoch, is_cuda, log_interval,
              print_progress=True):
        model.train()
        global_epoch_loss = 0
        global_first_part = 0
        global_second_part = 0
        global_third_part = 0
        global_fourth_part = 0
        global_fifth_part = 0
        global_six_part = 0
        for batch_idx, (data, target, idx, kws_target) in enumerate(train_loader):
            if is_cuda:
                data, target = data.cuda(), target.cuda()
            optimizer.zero_grad()
            output, counter_output = model(data)
            loss, first_part, second_part, third_part, fourth_part, fifth_part, six_part = loss_func(output,
                                                                                                     counter_output,
                                                                                                     target,
                                                                                                     config_dict,
                                                                                                     is_cuda)
            loss.backward()
            optimizer.step()
            global_epoch_loss += loss.item()
            global_first_part += first_part.item()
            global_second_part += second_part.item()
            global_third_part += third_part.item()
            global_fourth_part += fourth_part.item()
            global_fifth_part += fifth_part.item()
            global_six_part += six_part.item()

            if print_progress:
                if batch_idx % log_interval == 0:
                    print('Train Epoch: {} [{}/{} ({:.0f}%)]\tLoss: {:.6f}'.format(
                        epoch, batch_idx * len(data), len(train_loader.dataset), 100.
                               * batch_idx / len(train_loader), loss.item()))
        return global_epoch_loss / len(train_loader.dataset), global_first_part / len(train_loader.dataset), \
               global_second_part / len(train_loader.dataset), global_third_part / len(train_loader.dataset), \
               global_fourth_part / len(train_loader.dataset), global_fifth_part / len(
            train_loader.dataset), global_six_part / len(train_loader.dataset)

    @staticmethod
    def yolo_accuracy(prediction, count_output, target, C, B, K, T, iou_t=0.5, is_cuda=False):
        correct_class_high_iou = 0
        correct_class_low_iou = 0
        wrong_class_high_iou = 0
        wrong_class_low_iou = 0
        total_correct_class = 0
        pred_ws, pred_start, pred_end, pred_conf, pred_class_all_prob = utils.extract_data(prediction, C, B, K)

        # added
        k_word = target[:, :, B * 3:-1]
        total_per_cell_y_true = torch.sum(k_word, dim=2)
        total_y_true = torch.sum(total_per_cell_y_true, dim=1)
        _, pred_counter = torch.max(count_output, 1)
        # print("pred_counter: ", pred_counter)
        # print("total_y_true: ", total_y_true)
        true_count = (torch.sum(pred_counter == total_y_true)).item()
        all_count = pred_counter.shape[0]  # number of predictions/examples
        accuracy_count = (true_count / all_count) * 100

        pred_classes_prob, pred_classes = torch.max(pred_class_all_prob, 3)
        conf_class_mult, box_index = torch.max((pred_conf * pred_classes_prob), 2)

        no_object_correct = torch.eq((conf_class_mult < T).float(), 1 - target[:, :, -1]).cpu().sum()
        no_object_object_wrong = (torch.eq((conf_class_mult < T).float(), target[:, :, -1])).cpu().sum()

        target_ws, target_start, target_end, target_conf, target_class_all_prob = utils.extract_data(target[:, :, :-1],
                                                                                                     C,
                                                                                                     B, K)
        target_classes_prob, target_classes = torch.max(target_class_all_prob, 3)

        squeeze_target_start = torch.zeros([target_start.size(0), C]).cuda() if is_cuda else \
            torch.zeros([target_start.size(0), C])
        squeeze_pred_start = torch.zeros([target_start.size(0), C]).cuda() if is_cuda else \
            torch.zeros([target_start.size(0), C])
        squeeze_target_end = torch.zeros([target_start.size(0), C]).cuda() if is_cuda else \
            torch.zeros([target_start.size(0), C])
        squeeze_pred_end = torch.zeros([target_start.size(0), C]).cuda() if is_cuda else \
            torch.zeros([target_start.size(0), C])
        squeeze_target_ws = torch.zeros([target_start.size(0), C]).cuda() if is_cuda else \
            torch.zeros([target_start.size(0), C])
        squeeze_pred_ws = torch.zeros([target_start.size(0), C]).cuda() if is_cuda else \
            torch.zeros([target_start.size(0), C])

        box_indices_array = box_index.cpu().numpy()
        for row in range(0, box_indices_array.shape[0]):
            for col in range(0, box_indices_array.shape[1]):
                squeeze_target_start[row, col] = target_start[row, col, box_indices_array[row, col]]
                squeeze_pred_start[row, col] = pred_start[row, col, box_indices_array[row, col]]
                squeeze_target_end[row, col] = target_end[row, col, box_indices_array[row, col]]
                squeeze_pred_end[row, col] = pred_end[row, col, box_indices_array[row, col]]
                squeeze_target_ws[row, col] = target_ws[row, col, box_indices_array[row, col]]
                squeeze_pred_ws[row, col] = pred_ws[row, col, box_indices_array[row, col]]

        intersect_start = torch.max(squeeze_pred_start, squeeze_target_start)
        intersect_end = torch.min(squeeze_pred_end, squeeze_target_end)
        intersect_w = intersect_end - intersect_start

        zero_w = torch.zeros(intersect_w.shape, dtype=torch.float).cuda()
        intersect_w_new = torch.max(intersect_w, zero_w)

        iou_mask = torch.eq(torch.eq((conf_class_mult > T).float(), target[:, :, -1]).float(), target[:, :, -1])
        # iou = intersect_w / (squeeze_pred_ws + squeeze_target_ws - intersect_w)
        iou = intersect_w_new / (squeeze_pred_ws + squeeze_target_ws - intersect_w_new)
        iou_select = iou * iou_mask.float()

        # ADDED
        count_classes_true = np.zeros(K + 1)
        count_classes_all_from_target = np.zeros(K + 1)

        mean_iou_correct = 0.0
        mean_iou_wrong = 0.0
        is_object = target[:, :, -1].cpu().numpy()
        for batch in range(0, box_indices_array.shape[0]):
            for cell in range(0, box_indices_array.shape[1]):
                if is_object[batch, cell].item() != 1 or (conf_class_mult > T)[batch, cell].item() != 1:
                    continue
                # ADDED
                # count how many from each class
                count_classes_all_from_target[target_classes[batch, cell, 0].item()] += 1

                if pred_classes[batch, cell, 0].item() != target_classes[
                    batch, cell, 0].item():  # predict object with wrong class
                    if iou_select[batch, cell].item() < iou_t:
                        wrong_class_low_iou += 1
                    else:
                        wrong_class_high_iou += 1

                    mean_iou_wrong += iou_select[batch, cell].item()
                else:  # predict object with right class
                    # ADDED
                    # count predict right class
                    count_classes_true[target_classes[batch, cell, 0].item()] += 1

                    if iou_select[batch, cell].item() < iou_t:
                        correct_class_low_iou += 1
                    else:
                        correct_class_high_iou += 1
                    mean_iou_correct += iou_select[batch, cell].item()

                total_correct_class += 1

        return no_object_correct - total_correct_class, no_object_object_wrong, correct_class_high_iou, \
               correct_class_low_iou, wrong_class_high_iou, wrong_class_low_iou, total_correct_class, \
               mean_iou_correct, mean_iou_wrong, count_classes_true, count_classes_all_from_target, true_count, all_count

    @staticmethod
    def test(loader, model, loss_func, config_dict, threshold, iou_threshold, is_cuda, print_progress=False):
        with torch.no_grad():
            model.eval()
            test_loss = 0
            total = 0
            global_first_part = 0
            global_second_part = 0
            global_third_part = 0
            global_fourth_part = 0
            global_fifth_part = 0
            global_six_part = 0
            C = config_dict["C"]
            B = config_dict["B"]
            K = config_dict["K"]

            no_object_correct = 0  # no object and didn't find an object
            no_object_object_wrong = 0
            correct_class_high_iou = 0
            correct_class_low_iou = 0
            wrong_class_high_iou = 0
            wrong_class_low_iou = 0
            total_correct_class = 0
            total_mean_iou_correct = 0
            total_mean_iou_wrong = 0
            total_object = 0
            total_no_object = 0
            accuracy_values = np.zeros(7)

            # ADDED
            all_count_classes_true = np.zeros(K + 1)
            all_count_classes_all_from_target = np.zeros(K + 1)

            global_all_count = 0
            global_true_all_count = 0

            for data, target, idx, kws_target in loader:
                if is_cuda:
                    data, target = data.cuda(), target.cuda()
                output, counter_output = model(data)
                all, first_part, second_part, third_part, fourth_part, fifth_part, six_part = loss_func(output,
                                                                                                        counter_output,
                                                                                                        target,
                                                                                                        config_dict,
                                                                                                        is_cuda)
                test_loss += all
                global_first_part += first_part
                global_second_part += second_part
                global_third_part += third_part
                global_fourth_part += fourth_part
                global_fifth_part += fifth_part
                global_six_part += six_part

                accuracy_values[0], accuracy_values[1], accuracy_values[2], accuracy_values[3], accuracy_values[4], \
                accuracy_values[5], accuracy_values[6], mean_iou_correct, mean_iou_wrong, \
                count_classes_true, count_classes_all_from_target, true_count, all_count = \
                    TrainSpeechYolo.yolo_accuracy(output, counter_output, target, C, B, K, threshold, iou_threshold, is_cuda)

                # ADDED
                all_count_classes_true += count_classes_true
                all_count_classes_all_from_target += count_classes_all_from_target

                global_true_all_count += true_count
                global_all_count += all_count

                no_object_correct += accuracy_values[0]
                no_object_object_wrong += accuracy_values[1]
                correct_class_high_iou += accuracy_values[2]
                correct_class_low_iou += accuracy_values[3]
                wrong_class_high_iou += accuracy_values[4]
                wrong_class_low_iou += accuracy_values[5]
                total_correct_class += accuracy_values[6]
                total_mean_iou_correct += mean_iou_correct
                total_mean_iou_wrong += mean_iou_wrong

                current_total = target.size(0) * C
                current_object = target[:, :, -1].sum().item()
                total += current_total
                total_no_object += current_total - current_object
                total_object += current_object

                # exit()

            test_loss /= len(loader.dataset)
            global_first_part /= len(loader.dataset)
            global_second_part /= len(loader.dataset)
            global_third_part /= len(loader.dataset)
            global_fourth_part /= len(loader.dataset)
            global_fifth_part /= len(loader.dataset)
            global_six_part /= len(loader.dataset)

        # should prevent nans
        if no_object_object_wrong == 0:
            no_object_object_wrong_ratio = 0
        else:
            no_object_object_wrong_ratio = 100. * no_object_object_wrong / total

        if no_object_correct == 0:
            no_object_correct_ratio = 0
        else:
            no_object_correct_ratio = 100. * no_object_correct / total_no_object

        if total_correct_class == 0:
            total_correct_class_ratio = 0
        else:
            total_correct_class_ratio = 100. * total_correct_class / total_object

        if correct_class_high_iou == 0:
            correct_class_high_iou_ratio = 0
        else:
            correct_class_high_iou_ratio = 100. * correct_class_high_iou / total_correct_class

        if correct_class_low_iou == 0:
            correct_class_low_iou_ratio = 0
        else:
            correct_class_low_iou_ratio = 100. * correct_class_low_iou / total_correct_class

        if wrong_class_high_iou == 0:
            wrong_class_high_iou_ratio = 0
        else:
            wrong_class_high_iou_ratio = 100. * wrong_class_high_iou / total_correct_class

        if wrong_class_low_iou == 0:
            wrong_class_low_iou_ratio = 0
        else:
            wrong_class_low_iou_ratio = 100. * wrong_class_low_iou / total_correct_class

        if (correct_class_high_iou + correct_class_low_iou) == 0:
            total_mean_iou_correct = 0
        else:
            total_mean_iou_correct = total_mean_iou_correct / (correct_class_high_iou + correct_class_low_iou)

        if (wrong_class_high_iou + wrong_class_low_iou) == 0:
            total_mean_iou_wrong = 0
        else:
            total_mean_iou_wrong = total_mean_iou_wrong / (wrong_class_high_iou + wrong_class_low_iou)

        if print_progress:
            # ADDED
            classes_to_int = loader.dataset.class_to_idx
            # for each key - print th name and total correct from all
            for key in classes_to_int.keys():
                if all_count_classes_all_from_target[classes_to_int[key]] != 0:
                    correct = (all_count_classes_true[classes_to_int[key]]) / (
                        all_count_classes_all_from_target[classes_to_int[key]]) * 100
                else:
                    correct = 0
                print('Class {} : correct : {}/{} ({:.0f}%)'.format(key, all_count_classes_true[classes_to_int[key]],
                                                                    all_count_classes_all_from_target[
                                                                        classes_to_int[key]],
                                                                    correct))
            correct_count_acc = (global_true_all_count / global_all_count) * 100

            print('Number of vowels in all examples : correct : {}/{} ({:.0f}%)'.format(global_true_all_count,
                                                                                        global_all_count,
                                                                                        correct_count_acc))

            print('\nAverage Global Six Part Loss: {:.4f},\n Test set: Average loss: {:.4f}, \n '
                  'mistake: {}/{} ({:.0f}%) , correct no object: {}/{} ({:.0f}%) , correct object: {}/{} ({:.0f}%) \n'
                  'correct class high iou: {}/{} ({:.0f}%) correct class low iou: {}/{} ({:.0f}%)   mean iou {}\n'
                  'wrong class high iou: {}/{} ({:.0f}%) wrong class low iou: {}/{} ({:.0f}%)    mean iou {}\n'.format(
                global_six_part, test_loss, no_object_object_wrong, total, no_object_object_wrong_ratio,
                no_object_correct, total_no_object, no_object_correct_ratio,
                total_correct_class, total_object, total_correct_class_ratio,
                correct_class_high_iou, total_correct_class, correct_class_high_iou_ratio,
                correct_class_low_iou, total_correct_class, correct_class_low_iou_ratio, total_mean_iou_correct,
                wrong_class_high_iou, total_correct_class, wrong_class_high_iou_ratio,
                wrong_class_low_iou, total_correct_class, wrong_class_low_iou_ratio, total_mean_iou_wrong)),

        return test_loss, global_six_part, total_correct_class_ratio, no_object_object_wrong_ratio

    @staticmethod
    def evaluation_measures(loader, model, threshold, config_dict, is_cuda):
        t_cuda = torch.cuda if is_cuda else torch
        with torch.no_grad():
            model.eval()

            num_classes = config_dict['K']
            total_acc_per_term = np.zeros((num_classes, 3))  # np.zeros((NUM_CLASSES,3)) #tp, fp, fn
            total_actual_lens = np.zeros(2)
            for batch_idx, (data, target, idx, kws_target) in enumerate(loader):

                if is_cuda:
                    data, target = data.cuda(), target.cuda()
                output, counter_output = model(data)

                acc_per_term, actual_lens = TrainSpeechYolo.eval_actual(output, target, threshold, config_dict)
                total_acc_per_term += acc_per_term
                total_actual_lens += actual_lens

        f1_per_term = np.zeros(num_classes)
        precision = 0
        # calculate F1 score for each class
        for item in range(len(total_acc_per_term)):
            if total_acc_per_term[item][0] + total_acc_per_term[item][1] + total_acc_per_term[item][2] == 0:
                continue  # zeros
            f1_per_term[item] = (2 * total_acc_per_term[item][0]) / (
                    2 * total_acc_per_term[item][0] + total_acc_per_term[item][1] + total_acc_per_term[item][2])

        # precision: TP/(TP + FP)
        temp_acc_sum = np.sum(total_acc_per_term, 0)  # collapsing K dimension

        if float(temp_acc_sum[0]) == 0:
            precision = 0
        else:
            precision = float(temp_acc_sum[0]) / float(temp_acc_sum[0] + temp_acc_sum[1])

        if float(temp_acc_sum[0]) == 0:
            recall = 0
        else:
            recall = float(temp_acc_sum[0]) / float(temp_acc_sum[0] + temp_acc_sum[2])

        if float(temp_acc_sum[0]) + float(temp_acc_sum[1]) + float(temp_acc_sum[2]) == 0:
            f1 = 0
        else:
            f1 = (2 * float(temp_acc_sum[0])) / (
                    2 * float(temp_acc_sum[0]) + float(temp_acc_sum[1]) + float(temp_acc_sum[2]))

        print('threshold: {}'.format(threshold))
        print('Actual Accuracy (Val): {}'.format(float(total_actual_lens[0]) / total_actual_lens[1]))
        print('F1 regular mean: {}'.format(np.mean(f1)))
        print('precision: {}'.format(precision))
        print('recall: {}'.format(recall))
        print('**************')

    @staticmethod
    def convert_yolo_tags(pred, c, b, k, threshold):
        '''
        YOLO's outputs are tags given in format: (cell_i, box_j, (t, delta_t, p_b_{i,j}), p_{c_i}(k) ).
        This function converts it to tags in the following format: (start, end, word)

        inputs:
        pred: prediction or given target labels, in yolo format
        c: number of cells
        b: number of timing boxes
        k: number of keywords
        threshold: if the product of: p_b_{i,j} * p_{c_i}(k) is greather than the threshold, we predict that a keyword exists.

        output:
        final_pred_labels: dictionary, whose keys are the keywords. Every keyword has an array of (start, end) values.

        '''

        pred_ws, pred_start, pred_end, pred_conf, pred_class_prob = utils.extract_data(pred, c, b, k)
        class_max, class_indices = torch.max(pred_class_prob, 3)
        conf_max, box_indices = torch.max((pred_conf * class_max), 2)

        pass_conf = (conf_max >= threshold).float()
        labels = []
        for batch in range(0, pred.size(0)):
            for cell_i in range(0, pred.size(1)):
                if pass_conf[batch, cell_i].item() <= 0:
                    continue
                selected_box_index = box_indices[batch, cell_i].item()
                selected_class_index = class_indices[batch, cell_i, 0].item()
                label_start = pred_start[batch, cell_i, selected_box_index].item()
                label_end = pred_end[batch, cell_i, selected_box_index].item()
                x = (label_end + label_start) / 2
                w = pred_ws[batch, cell_i, selected_box_index].item()
                labels.append([cell_i, x, w, selected_class_index, batch])

        width_cell = 1. / c  # width per cell
        final_pred_labels = {}

        for label in labels:
            real_x = (label[0] * width_cell + label[1])  # label[1] was already multiple with width cell
            real_w = label[2]
            cur_start = (real_x - float(real_w) / 2.0)
            cur_end = (real_x + float(real_w) / 2.0)
            cur_class = str(label[4]) + "_" + str(label[3])  # batch_class

            if cur_class not in final_pred_labels:
                final_pred_labels[cur_class] = []

            else:
                prev_start = final_pred_labels[cur_class][-1][0]
                prev_end = final_pred_labels[cur_class][-1][1]
                if cur_start >= prev_end and cur_end >= prev_start:
                    # --------
                    #          -------
                    if cur_end - prev_end <= GAP_THRESH:
                        final_pred_labels[cur_class].pop()  # remove last item
                        cur_start = prev_start
                elif cur_start <= prev_end and prev_start <= cur_end:
                    # --------
                    #      -------
                    final_pred_labels[cur_class].pop()  # remove last item
                    cur_start = prev_start
                elif cur_start >= prev_start and cur_end <= prev_end:
                    # -----------
                    #    ----
                    final_pred_labels[cur_class].pop()  # remove last item
                    cur_start = prev_start
                    cur_end = pred_end
                elif cur_start >= prev_start and cur_end >= pred_end:
                    #     -----
                    #   ---------
                    final_pred_labels[cur_class].pop()  # remove last item

            final_pred_labels[cur_class].append([cur_start, cur_end])
            # print "objet- start:{}, end:{}, class:{}".format(pred_start,pred_end, pred_class)

        return final_pred_labels


    @staticmethod
    def counter_for_actual_accuracy(pred_labels, target_labels):  # find position for eval_actual

        # given list of targets and predictions, find which prediction corresponds to which target.
        iou_choice_counter = 0
        mega_iou_choice = []
        for key, pred_label_list in pred_labels.items():
            if key in target_labels:

                iou_list = []
                target_label_list = target_labels[key]
                for target_idx, target_label in enumerate(target_label_list):

                    for pred_idx, pred_label in enumerate(pred_label_list):
                        iou_val = utils.calc_iou(pred_label, target_label)
                        iou_list.append([iou_val, pred_idx, target_idx, pred_label, target_label])

                list_len = min(len(target_label_list), len(pred_label_list))
                iou_list = sorted(iou_list, key=lambda k: (k[0], random.random()), reverse=True)
                iou_choice = []
                while len(iou_list) != 0 and len(iou_choice) < list_len:
                    if len(iou_choice) == 0:
                        iou_choice.append(iou_list.pop(0))
                    else:
                        # pdb.set_trace()
                        cur_item = iou_list.pop(0)
                        flag = True
                        for item in iou_choice:
                            if cur_item[1] == item[1]:
                                flag = False
                                break
                            if cur_item[2] == item[2]:
                                flag = False
                                break
                        if flag:
                            iou_choice.append(cur_item)

                mega_iou_choice.extend(iou_choice)

        # ============================================================================================

        # for actual accuracy: check if center of prediction is within (start, end) boundaries of target
        for item in mega_iou_choice:
            iou_val, pred_idx, target_idx, pred_label, target_label = item
            pred_start, pred_end = pred_label
            target_start, target_end = target_label

            center_pred = float(pred_end + pred_start) / 2

            if round(center_pred, 2) >= round(target_start, 2) and round(center_pred, 2) <= round(target_end, 2):
                iou_choice_counter += 1

        return iou_choice_counter

    @staticmethod
    def eval_actual(yolo_output, target, threshold, config_dict):
        C = config_dict["C"]
        B = config_dict["B"]
        K = config_dict["K"]

        actual_lens = np.zeros(2)  # num_position_correct, len(target_labels

        pred_labels = TrainSpeechYolo.convert_yolo_tags(yolo_output, C, B, K, threshold)
        target_labels = TrainSpeechYolo.convert_yolo_tags(target[:, :, :-1], C, B, K, threshold)

        num_position_correct = TrainSpeechYolo.counter_for_actual_accuracy(pred_labels, target_labels)  # find position for eval_actual

        num_classes = config_dict['K']
        acc_per_term = np.zeros((num_classes, 3))  # tp, fp, fn
        f1_per_term = np.zeros(num_classes)
        for pred_key, pred_list in pred_labels.items():  # dict of keys "batch_wordIdx"
            pred_word = int(pred_key.split('_')[1])
            if pred_key in target_labels:

                target_list = target_labels[pred_key]
                len_target = len(target_list)
                len_pred = len(pred_list)
                if len_target == len_pred:
                    acc_per_term[pred_word][0] += len_target  # true positive
                if len_target < len_pred:
                    acc_per_term[pred_word][1] += len_pred - len_target  # false positive
                    acc_per_term[pred_word][0] += len_target  # true positive
                if len_target > len_pred:
                    # not calculating "miss" here
                    acc_per_term[pred_word][0] += len_pred

            else:
                acc_per_term[pred_word][1] += 1  # false positive

        count_existance = np.zeros(K)
        exists_counter = 0
        for target_key, target_list in target_labels.items():
            target_word = int(target_key.split('_')[1])
            count_existance[target_word] += len(target_list)
            exists_counter += len(target_list)

        for item in range(len(acc_per_term)):  # false negative == miss
            acc_per_term[item][2] = count_existance[item] - acc_per_term[item][0]

        actual_lens[0], actual_lens[1] = num_position_correct, exists_counter

        return acc_per_term, actual_lens

