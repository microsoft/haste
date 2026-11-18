#include <arpa/inet.h>
#include <openssl/bio.h>
#include <openssl/evp.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

int main(void)
{
    int server = -1, client = -1, result = 1;
    struct sockaddr_in6 expected = {0};
    struct in6_addr actual;
    socklen_t address_length = sizeof(expected);
    size_t actual_length = sizeof(actual);
    BIO *bio = NULL;
    BIO_ADDR *peer = NULL;
    EVP_CIPHER *cipher = NULL;

    server = socket(AF_INET6, SOCK_DGRAM, 0);
    client = socket(AF_INET6, SOCK_DGRAM, 0);
    if (server < 0 || client < 0)
        goto out;
    expected.sin6_family = AF_INET6;
    expected.sin6_addr = in6addr_loopback;
    if (bind(server, (struct sockaddr *)&expected, sizeof(expected)) != 0
        || getsockname(server, (struct sockaddr *)&expected, &address_length) != 0
        || connect(client, (struct sockaddr *)&expected, sizeof(expected)) != 0)
        goto out;
    bio = BIO_new_dgram(client, BIO_NOCLOSE);
    peer = BIO_ADDR_new();
    cipher = EVP_CIPHER_fetch(NULL, "AES-128-GCM-SIV", NULL);
    if (bio == NULL || peer == NULL || cipher == NULL
        || !BIO_dgram_detect_peer_addr(bio, peer)
        || BIO_ADDR_family(peer) != AF_INET6
        || !BIO_ADDR_rawaddress(peer, &actual, &actual_length)
        || actual_length != sizeof(actual)
        || memcmp(&actual, &expected.sin6_addr, sizeof(actual)) != 0
        || BIO_ADDR_rawport(peer) != expected.sin6_port)
        goto out;
    result = 0;
out:
    if (result != 0)
        fprintf(stderr, "OpenSSL IPv6 datagram peer detection failed\n");
    BIO_ADDR_free(peer);
    BIO_free(bio);
    EVP_CIPHER_free(cipher);
    if (client >= 0)
        close(client);
    if (server >= 0)
        close(server);
    return result;
}
