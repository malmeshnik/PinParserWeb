from apps.results.models import PinResult


class PinPersistService:

    @staticmethod
    def from_network(task, keyword: str, pins: list[dict]):
        objects = []

        for pin in pins:
            pin_id = pin.get("id")
            if not pin_id:
                continue

            images = pin.get("images", {})
            orig = images.get("orig", {})

            objects.append(
                PinResult(
                    task=task,
                    keyword=keyword,
                    pin_id=pin_id,
                    pin_url=f"https://www.pinterest.com/pin/{pin_id}/",
                    title=pin.get("title"),
                    description=pin.get("description"),
                    image_url=orig.get("url"),
                    domain=pin.get("domain"),
                    alt_text=pin.get("grid_title"),
                    annotation=pin.get("board", {}).get("name"),
                    saves=pin.get("reaction_counts", {}).get("1"),
                    pinner_username=pin.get("pinner", {}).get("username"),
                    creation_date=pin.get("created_at"),
                )
            )

        PinResult.objects.bulk_create(
            objects,
            ignore_conflicts=True,  # (task, pin_url)
            batch_size=500,
        )

    @staticmethod
    def from_dom(task, keyword: str, urls: list[str]):
        objects = []

        for url in urls:
            objects.append(
                PinResult(
                    task=task,
                    keyword=keyword,
                    pin_url=url,
                )
            )

        PinResult.objects.bulk_create(
            objects,
            ignore_conflicts=True,
            batch_size=500,
        )
