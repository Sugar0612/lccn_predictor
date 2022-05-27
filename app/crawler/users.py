import asyncio
from typing import List, Optional

import httpx
from beanie.odm.operators.update.general import Set

from app.crawler.utils import multi_http_request
from app.db.models import ContestRecordArchive, User, ContestRecordPredict


async def multi_upsert_user(
        graphql_response_list: List[Optional[httpx.Response]],
        multi_request_list: List[ContestRecordPredict | ContestRecordArchive],
) -> None:
    update_tasks = list()
    for response, contest_record in zip(graphql_response_list, multi_request_list):
        if response is None:
            print(f"warning: contest_record={contest_record} user query response is None")
            continue
        data = response.json().get("data", {}).get("userContestRanking")
        if data is None:
            print(f"warning: contest_record={contest_record} user query data is None")
            continue
        print(contest_record, data)
        user = User(
            username=contest_record.username,
            user_slug=contest_record.user_slug,
            data_region=contest_record.data_region,
            attendedContestsCount=data.get("attendedContestsCount"),
            rating=data.get("rating"),
        )
        update_tasks.append(
            User.find_one(
                User.username == user.username,
                User.data_region == user.data_region,
            ).upsert(
                Set(
                    {
                        User.update_time: user.update_time,
                        User.attendedContestsCount: user.attendedContestsCount,
                        User.rating: user.rating,
                    }
                ),
                on_insert=user
            )
        )
    await asyncio.gather(*update_tasks)


async def multi_request_user_cn(
        cn_multi_request_list: List[ContestRecordPredict | ContestRecordArchive],
) -> None:
    cn_response_list = await multi_http_request(
        {
            contest_record.user_slug: {
                "url": "https://leetcode-cn.com/graphql/noj-go/",
                "method": "POST",
                "json": {
                    "query": """
                             query userContestRankingInfo($userSlug: String!) {
                                    userContestRanking(userSlug: $userSlug) {
                                        attendedContestsCount
                                        rating
                                    }
                                }
                             """,
                    "variables": {"userSlug": contest_record.user_slug},
                },
            }
            for contest_record in cn_multi_request_list
        },
        concurrent_num=10,
    )
    await multi_upsert_user(cn_response_list, cn_multi_request_list)
    cn_multi_request_list.clear()


async def multi_request_user_us(
        us_multi_request_list: List[ContestRecordPredict | ContestRecordArchive],
) -> None:
    us_response_list = await multi_http_request(
        {
            contest_record.username: {
                "url": "https://leetcode.com/graphql/",
                "method": "POST",
                "json": {
                    "query": """
                             query getContestRankingData($username: String!) {
                                userContestRanking(username: $username) {
                                    attendedContestsCount
                                    rating
                                }
                             }
                             """,
                    "variables": {"username": contest_record.username},
                },
            }
            for contest_record in us_multi_request_list
        },
        concurrent_num=10,
    )
    await multi_upsert_user(us_response_list, us_multi_request_list)
    us_multi_request_list.clear()


async def upsert_users_from_a_contest(
        contest_name: str,
        in_predict_col: bool = True,
        concurrent_num: int = 200,
) -> None:
    if in_predict_col:
        to_be_queried = ContestRecordPredict.find_all(
            ContestRecordPredict.contest_name == contest_name,
        )
    else:
        to_be_queried = ContestRecordArchive.find_all(
            ContestRecordArchive.contest_name == contest_name,
        )
    cn_multi_request_list = list()
    us_multi_request_list = list()
    async for contest_record in to_be_queried:
        if len(cn_multi_request_list) + len(us_multi_request_list) >= concurrent_num:
            print(f"for loop run multi_request_list \n"
                  f"cn_multi_request_list{cn_multi_request_list}\n"
                  f"us_multi_request_list{us_multi_request_list}")
            await asyncio.gather(
                multi_request_user_cn(cn_multi_request_list),
                multi_request_user_us(us_multi_request_list),
            )
        if contest_record.data_region == "CN":
            cn_multi_request_list.append(contest_record)
        elif contest_record.data_region == "US":
            us_multi_request_list.append(contest_record)
        else:
            print(f"fatal error: data_region is not CN or US. contest_record={contest_record}")
    print(f"rest of run multi_request_list \n"
          f"cn_multi_request_list{cn_multi_request_list}\n"
          f"us_multi_request_list{us_multi_request_list}")
    await asyncio.gather(
        multi_request_user_cn(cn_multi_request_list),
        multi_request_user_us(us_multi_request_list),
    )


async def first_time_user_crawler() -> None:
    for i in range(293, 100, -1):
        await upsert_users_from_a_contest(contest_name=f"weekly-contest-{i}", in_predict_col=False)
    for i in range(78, 0, -1):
        await upsert_users_from_a_contest(contest_name=f"biweekly-contest-{i}", in_predict_col=False)


