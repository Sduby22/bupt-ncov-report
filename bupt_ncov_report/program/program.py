__all__ = (
    'Program',
)

import json
import logging
import sys
import traceback
from typing import List, Mapping, Optional, cast

import requests

from ..constant import *
from ..notifier import *
from ..predef import *
from ..program_utils import *

logger = logging.getLogger(__name__)


class Program:
    """
    程序的主入口，实现了主要的逻辑。
    使用本类时，直接调用 main 函数即可。
    本类提供状态码。状态码应用于外部代码退出此程序。
    """

    # 能在多个请求中复用的 HTTP header
    COMMON_HEADERS = {
        'User-Agent': HEADERS.UA,
        'Accept-Language': HEADERS.ACCEPT_LANG,
    }

    # 能在多个 POST 请求中复用的 HTTP header。不含 COMMON_HEADERS，请手动将这两个常量混合
    COMMON_POST_HEADERS = {
        'Accept': HEADERS.ACCEPT_JSON,
        'Origin': HEADERS.ORIGIN_BUPTAPP,
        'X-Requested-With': HEADERS.REQUEST_WITH_XHR,
        'Content-Type': HEADERS.CONTENT_TYPE_UTF8,
    }

    def __init__(
            self, *,
            config: Mapping[str, Optional[ConfigValue]],
            program_utils: ProgramUtils,
            session: requests.Session,
            notifiers: List[INotifier],
    ):
        """
        :param config: 程序的配置
        :param program_utils: 类的依赖（我好想要依赖注入啊）
        :param session: 类的依赖（求求大佬们写个好用的 Python 依赖注入库吧）
        :param notifiers: INotifier 子类，用于通知用户执行结果（用参数传依赖太恶心了啊跪谢）
        """

        self._prog_util = program_utils
        self._sess = session
        self._notifiers = notifiers

        self._check_config(config)

        # 初始化整个 bupt_ncov_report 模块的根 logger
        self._initialize_logger(
            logging.getLogger('bupt_ncov_report'),
            cast(Optional[str], config.get('BNR_LOG_PATH')),
        )

        self._conf: Mapping[str, Optional[ConfigValue]] = config
        self._exit_status: int = 0

    def get_exit_status(self) -> int:
        return self._exit_status

    @staticmethod
    def _check_config(config: Mapping[str, Optional[ConfigValue]]) -> None:
        """
        检查程序配置是否正确；如不正确则抛出异常。
        :return: None
        """

        # 检查 BUPT SSO 用户名、密码
        for key in ('BUPT_SSO_USER', 'BUPT_SSO_PASS'):
            if config[key] is None:
                raise ValueError(f'配置 {key} 未设置。缺少此配置，该脚本无法自动登录北邮网站。')

        # 检查 Telegram 的环境变量是否已经设置
        if (config['TG_BOT_TOKEN'] is None) != (config['TG_CHAT_ID'] is None):
            raise ValueError('TG_BOT_TOKEN 和 TG_CHAT_ID 必须同时设置，否则程序无法正确运行。')

    @staticmethod
    def _initialize_logger(logger: logging.Logger, log_file: Optional[str]) -> None:
        """
        初始化传入的 Logger 对象，
        将 INFO 以上的日志输出到屏幕，将所有日志存入文件。
        :param logger: Logger 对象
        :param log_file: 日志文件路径
        :return: None
        """
        logger.setLevel(logging.DEBUG)

        # 将日志输出到控制台
        sh = logging.StreamHandler(sys.stdout)
        sh.setLevel(logging.INFO)
        sh.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))
        logger.addHandler(sh)

        # 将日志输出到文件
        if log_file:
            fh = logging.FileHandler(log_file, encoding='utf-8')
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
            logger.addHandler(fh)

    def do_ncov_report(self) -> str:
        """
        进行信息上报的工作函数，包含本脚本主要逻辑。
        :return: 上报 API 的返回内容。
        """
        # 登录北邮 nCoV 上报网站
        logger.info('登录北邮 nCoV 上报网站')
        login_res = self._sess.post(LOGIN_API, data={
            'username': cast(str, self._conf['BUPT_SSO_USER']),
            'password': cast(str, self._conf['BUPT_SSO_PASS']),
        }, headers={
            **self.COMMON_HEADERS,
            **self.COMMON_POST_HEADERS,
            'Referer': HEADERS.REFERER_LOGIN_API,
        })
        if login_res.status_code != 200:
            logger.debug(f'登录页：\n'
                         f'status code: {login_res.status_code}\n'
                         f'url: {login_res.url}')
            raise RuntimeError('登录 API 返回的 HTTP 状态码不是 200。')

        # 获取上报页面的数据
        report_page_res = self._sess.get(REPORT_PAGE, headers={
            **self.COMMON_HEADERS,
            'Accept': HEADERS.ACCEPT_HTML,
        })
        logger.debug(f'报告页：\n'
                     f'status code: {report_page_res.status_code}\n'
                     f'url: {report_page_res.url}')
        if report_page_res.status_code != 200:
            raise RuntimeError('上报页面的 HTTP 状态码不是 200。')
        if report_page_res.url != REPORT_PAGE:
            raise RuntimeError('访问上报页面时被重定向。一般来说原因是登录操作失败了；您的北邮账号和密码可能有误。')
        page_html = report_page_res.text
        if '每日上报' not in page_html:
            raise RuntimeError('上报页面的 HTML 中没有找到「每日上报」，可能已经改版。')

        # 从上报页面中提取 POST 的参数
        post_data = self._prog_util.extract_post_data(page_html)
        logger.debug(f'最终提交参数：{json.dumps(post_data)}')

        # 检查上报参数有没有异常
        if self._conf['STOP_WHEN_SICK']:
            verified_data = self._prog_util.verify_data(post_data)
            self._prog_util.check_data_sick(verified_data)

        # 最终 POST
        report_api_res = self._sess.post(
            REPORT_API,
            data=post_data,
            headers={
                **self.COMMON_HEADERS,
                **self.COMMON_POST_HEADERS,
                'Referer': HEADERS.REFERER_POST_API,
            },
        )
        if report_api_res.status_code != 200:
            raise RuntimeError(f'上报 API 返回的 HTTP 状态码（{report_api_res.status_code}）不是 200。')

        return report_api_res.text

    def do_dailyup_report(self) -> str:
        """
        进行信息上报的工作函数，包含本脚本主要逻辑。
        :return: 上报 API 的返回内容。
        """
        # 登录北邮 nCoV 上报网站
        logger.info('登录北邮 nCoV 上报网站')
        login_res = self._sess.post(LOGIN_API, data={
            'username': cast(str, self._conf['BUPT_SSO_USER']),
            'password': cast(str, self._conf['BUPT_SSO_PASS']),
        }, headers={
            **self.COMMON_HEADERS,
            **self.COMMON_POST_HEADERS,
            'Referer': HEADERS.REFERER_LOGIN_API,
        })
        if login_res.status_code != 200:
            logger.debug(f'登录页：\n'
                         f'status code: {login_res.status_code}\n'
                         f'url: {login_res.url}')
            raise RuntimeError('登录 API 返回的 HTTP 状态码不是 200。')

        # 获取上报页面的数据
        report_page_res = self._sess.get(DAILYUP_PAGE, headers={
            **self.COMMON_HEADERS,
            'Accept': HEADERS.ACCEPT_HTML,
        })
        logger.debug(f'报告页：\n'
                     f'status code: {report_page_res.status_code}\n'
                     f'url: {report_page_res.url}')
        if report_page_res.status_code != 200:
            raise RuntimeError('上报页面的 HTTP 状态码不是 200。')
        if report_page_res.url != DAILYUP_PAGE:
            raise RuntimeError('访问上报页面时被重定向。一般来说原因是登录操作失败了；您的北邮账号和密码可能有误。')
        page_html = report_page_res.text

        # 从上报页面中提取 POST 的参数
        post_data = self._prog_util.extract_post_data_dailyup(page_html)
        logger.debug(f'最终提交参数：{json.dumps(post_data)}')

        # 检查上报参数有没有异常
        if self._conf['STOP_WHEN_SICK']:
            verified_data = self._prog_util.verify_data(post_data)
            self._prog_util.check_data_sick(verified_data)

        # 最终 POST
        report_api_res = self._sess.post(
            DAILYUP_API,
            data=post_data,
            headers={
                **self.COMMON_HEADERS,
                **self.COMMON_POST_HEADERS,
                'Referer': HEADERS.REFERER_POST_API,
            },
        )
        if report_api_res.status_code != 200:
            raise RuntimeError(f'上报 API 返回的 HTTP 状态码（{report_api_res.status_code}）不是 200。')

        return report_api_res.text

    def main(self) -> str:
        """
        真正的主函数。
        该函数读取程序配置，并尝试调用工作函数；
        该函数随后获取工作函数的返回值或异常内容，通过 INotifier 发送给用户。

        :return: 通过 INotifier 发送的信息
        """
        # 运行工作函数
        logger.info('运行工作函数')
        success = True
        try:
            res = self.do_ncov_report()
        except:
            success = False
            res = traceback.format_exc()

        # 生成消息并打印到控制台
        if success:
            logger.info(f'成功：服务器的返回是：\n\n{res}')
        else:
            logger.info(f'失败：发生如下异常：\n\n{res}')

        # 将执行结果通过 INotifier 通知用户
        for notifier in self._notifiers:
            logger.info(f'通过「{notifier.PLATFORM_NAME}」给用户发送通知')
            try:
                notifier.notify(success=success, msg=res)
            except:
                logger.exception(f'使用「{notifier.PLATFORM_NAME}」通知失败，发生异常：')

        if not success:
            self._exit_status = 1
        return res

    def main2(self) -> str:
        """
        真正的主函数。
        该函数读取程序配置，并尝试调用工作函数；
        该函数随后获取工作函数的返回值或异常内容，通过 INotifier 发送给用户。

        :return: 通过 INotifier 发送的信息
        """
        # 运行工作函数
        logger.info('运行工作函数')
        success = True
        try:
            res = self.do_dailyup_report()
        except:
            success = False
            res = traceback.format_exc()

        # 生成消息并打印到控制台
        if success:
            logger.info(f'成功：服务器的返回是：\n\n{res}')
        else:
            logger.info(f'失败：发生如下异常：\n\n{res}')

        # 将执行结果通过 INotifier 通知用户
        for notifier in self._notifiers:
            logger.info(f'通过「{notifier.PLATFORM_NAME}」给用户发送通知')
            try:
                notifier.notify(success=success, msg=res)
            except:
                logger.exception(f'使用「{notifier.PLATFORM_NAME}」通知失败，发生异常：')

        if not success:
            self._exit_status = 1
        return res