__all__ = (
    'ProgramUtils',
)

import json
import logging
from typing import Any, Dict, List, Tuple, cast

from ..constant import *
from ..predef import *
from ..pure_utils import *

logger = logging.getLogger(__name__)


class ProgramUtils:
    """关系到疫情上报网站的具体逻辑的工具函数。"""

    def __init__(
            self,
            pure_utils: PureUtils,
    ):
        self.pure_util = pure_utils

    def extract_post_data(self, html: str) -> Dict[str, Any]:
        """
        从上报页面的 HTML 中，提取出上报 API 所需要填写的参数。
        该函数获取页面上 def 与 oldInfo 变量的值，将其正确混合后返回。

        :param html: 上报页 HTML
        :return: dict 类型，可用于最终上报时提交的参数
        """
        old_dict, new_dict = self.extract_old_new_data(html)

        # 需要从 new dict 中提取如下数据
        PICK_PROPS = (
            'id', 'uid', 'date', 'created',
        )

        for prop in PICK_PROPS:
            val = new_dict.get(prop, ...)
            if val is ...:
                raise RuntimeError(f'从网页上提取的 new data 中缺少属性 {prop}，可能网页已经改版。')

            old_dict[prop] = val

        return old_dict

    def extract_post_data_dailyup(self, html: str) -> Dict[str, Any]:
        """
        从上报页面的 HTML 中，提取出上报 API 所需要填写的参数。

        :param html: 上报页 HTML
        :return: dict 类型，可用于最终上报时提交的参数
        """
        old_dict = json.loads(html)['d']['info']

        # 需要从 old dict 中删除如下数据
        PICK_PROPS = (
            'created', 'creator', 'date', 'flag','id','uid'
        )

        for prop in PICK_PROPS:
            val = old_dict.pop(prop, None)
            if val is None:
                raise RuntimeError(f'从网页上提取的 old data 中缺少属性 {prop}，可能网页已经改版。')


        return old_dict

    def extract_old_new_data(self, html: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        从页面 HTML 中提取 def 变量与 oldInfo 变量的值（分别叫做 new 与 old data），并用 Python dict 的形式返回。
        当过短时，抛出异常。

        :param html: 上报页面的 HTML
        :return: 元组，(old_dict, new_dict)
        """

        new_data = self.pure_util.match_re_group1(r'var def = (\{.+\});', html)
        old_data = self.pure_util.match_re_group1(r'oldInfo: (\{.+\}),', html)

        # 检查数据是否足够长
        if len(old_data) < REASONABLE_LENGTH or len(new_data) < REASONABLE_LENGTH:
            raise ValueError('获取到的数据过短。请阅读脚本文档的「使用前提」部分。')

        old_dict, new_dict = json.loads(old_data), json.loads(new_data)
        return old_dict, new_dict

    def is_data_broken(self, data: Dict[str, Any]) -> bool:
        """
        检查最终上报数据内容是否破损（指出现不可能出现的值）
        （如果破损，可能是上报页面改版。）
        :param data: 最终上报的数据
        :return: True/False 表示是/否破损
        """
        # self.pure_util 太长了
        util = self.pure_util

        MUST_EXIST_PROPERTIES = (
            'tw', 'jcjgqr', 'remark', 'sfsfbh', 'ismoved',
        )
        for prop in MUST_EXIST_PROPERTIES:
            if prop not in data:
                return True

        # `tw` 数据必须在 1 到 9 之间
        if not util.is_number_data_in_range(data.get('tw'), (1, 10)):
            return True

        # `jcjgqr` 必须在 0 到 3 之间
        if not util.is_number_data_in_range(data.get('jcjgqr'), (0, 4)):
            return True

        # 值为 0 或 1 的属性
        BINARY_PROPERTIES = (
            'zgfxdq', 'sfcxtz', 'sfjcbh', 'mjry',
            'csmjry', 'sfcyglq', 'szsqsfybl', 'sfcxzysx',
        )

        for prop in BINARY_PROPERTIES:
            if not util.is_number_data_in_range(data.get(prop), (0, 2)):
                return True

        return False

    def verify_data(self, data: Dict[str, Any]) -> VerifiedData:
        """
        验证 data 是否是破损的；如果 data 未破损，则原样返回。此处使用类型系统保证正确性。
        :param data: 最终上报数据
        :return: data 本身
        """
        if self.is_data_broken(data):
            raise RuntimeError('要上报的数据似乎是破损的，可能网页已经改版。'
                               '此时无法使用 STOP_WHEN_SICK 功能；上报失败，请手动上报。')

        # 仅用于类型检查器的类型转换
        return cast(VerifiedData, data)

    def data_sick_report(self, data: VerifiedData) -> List[str]:
        """
        检测当前数据中表示生病的项，生成「生病项报告」。
        如：体温 38.5°C，「其他信息」不为空，接触过疑似确诊人群等。

        :param data: 最终上报的数据，必须经过检查确定其未破损
        :return: str 数组，其中每一条为一个异常项。无异常则为空 list
        """

        abnormal_items = []

        # 体温：>= 37°C 则为异常
        body_temp = int(data['tw'])
        if body_temp > 3:
            abnormal_items.append('您上一次填报了高于 37 度的体温')

        current_situation = int(data['jcjgqr'])
        if current_situation != 0:
            abnormal_items.append('您当前状态为疑似感染/确诊感染/其他')

        if isinstance(data['remark'], str) and data['remark'].strip() != '':
            abnormal_items.append('您的「其他信息」一栏不为空')

        if self.pure_util.looks_truthy(data['sfsfbh']) or self.pure_util.looks_truthy(data['ismoved']):
            abnormal_items.append('您可能昨天或今天去了别的地方，导致位置有变化；现在提交将导致数据异常，请您今天手动提交')

        BINARY_PROPERTIES = {
            'zgfxdq': '是否在中高风险地区',
            'sfcxtz': '是否出现症状',
            'sfjcbh': '是否接触感染人群',
            'mjry': '是否接触‘密切接触’人员',
            'csmjry': '是否去过疫情场所',
            'sfcyglq': '是否处于观察期',
            'szsqsfybl': '所在社区是否有确诊病例',
            'sfcxzysx': '是否有值得注意的情况',
        }

        for prop, desc in BINARY_PROPERTIES.items():
            if self.pure_util.looks_truthy(data[prop]):
                abnormal_items.append(f'「{desc}」，您填了「是」')

        return abnormal_items

    def check_data_sick(self, data: VerifiedData) -> None:
        """
        如果提交的数据表明用户生病，则抛出异常。

        :param data: 最终提交数据，必须经过检查确定其未破损
        :return: None
        """
        # 获取生病列表
        sick_list = self.data_sick_report(data)
        if len(sick_list) == 0:
            return

        # 格式化生病列表
        err_msg: List[str] = ['\n您上一次填报的数据中，以下数据异常：\n']
        for i in sick_list:
            err_msg.append('· ' + i)
        err_msg.append('\n由于您开启了 STOP_WHEN_SICK 配置，且检测到您数据为异常数据，自动上报失败；'
                       '请您今天手动填报正常数据，从明天开始再自动填报。')

        raise RuntimeError('\n'.join(err_msg))
